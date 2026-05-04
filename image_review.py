#!/usr/bin/env python3
"""SIIL Gallery — keep/delete decisions on a folder of generated images.

Each batch lives under a folder in DATA_DIR. The app shows a feed of cards,
one per image, with Keep / Delete buttons. Delete really removes the file.
"Upload to Canva" button takes all kept images and uploads them via the
Canva REST API.

Run:
    pip install flask requests
    DATA_DIR=/home/siil_ostomy/image-review/data python image_review.py
    # binds to 127.0.0.1:8196 by default

Canva env (set in /home/siil_ostomy/image-review/.env):
    CANVA_API_TOKEN     — OAuth access token from Canva Developer portal
    CANVA_FOLDER_ID     — (optional) default folder to drop assets in
    PUBLIC_BASE_URL     — public URL prefix for image serving (used in upload-from-url)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import pathlib
import re
import secrets
import shutil
import time
import urllib.parse
from html import escape
from flask import Flask, jsonify, request, send_file, abort, redirect, url_for
import requests

DATA_DIR = pathlib.Path(os.environ.get("DATA_DIR", "/home/siil_ostomy/image-review/data")).resolve()
TRASH_DIR = DATA_DIR.parent / "trash"
DECISIONS_FILE = DATA_DIR.parent / "decisions.json"
CANVA_LOG = DATA_DIR.parent / "canva_uploads.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TRASH_DIR.mkdir(parents=True, exist_ok=True)

# Auto-load .env if present (avoid needing an extra dep)
ENV_FILE = DATA_DIR.parent / ".env"
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

CANVA_API_TOKEN = os.environ.get("CANVA_API_TOKEN", "")
CANVA_REFRESH_TOKEN = os.environ.get("CANVA_REFRESH_TOKEN", "")
CANVA_CLIENT_ID = os.environ.get("CANVA_CLIENT_ID", "")
CANVA_CLIENT_SECRET = os.environ.get("CANVA_CLIENT_SECRET", "")  # optional for confidential clients
CANVA_TOKEN_FILE = DATA_DIR.parent / "canva_token.json"
CANVA_FOLDER_ID = os.environ.get("CANVA_FOLDER_ID", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://static.253.118.104.178.clients.your-server.de/review")

# OAuth re-authorization (added 2026-05-04 — token lineage was revoked, refresh dies forever)
CANVA_AUTHORIZE_URL = "https://www.canva.com/api/oauth/authorize"
CANVA_TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
CANVA_SCOPES = "app:read asset:read asset:write design:content:read design:content:write design:meta:read folder:read folder:write"
CANVA_OAUTH_STATE_FILE = DATA_DIR.parent / ".canva_oauth_state.json"


def _load_canva_token() -> str:
    """Return current access token. Refreshes via refresh_token if cached file is fresher."""
    global CANVA_API_TOKEN
    if CANVA_TOKEN_FILE.exists():
        try:
            d = json.loads(CANVA_TOKEN_FILE.read_text())
            if d.get("access_token") and d.get("expires_at", 0) > time.time() + 60:
                return d["access_token"]
        except Exception:
            pass
    return CANVA_API_TOKEN


def _refresh_canva_token() -> str | None:
    """Use refresh_token to fetch a new access_token. Persist to disk."""
    if not CANVA_REFRESH_TOKEN or not CANVA_CLIENT_ID:
        return None
    body = {
        "grant_type": "refresh_token",
        "refresh_token": CANVA_REFRESH_TOKEN,
        "client_id": CANVA_CLIENT_ID,
    }
    if CANVA_CLIENT_SECRET:
        body["client_secret"] = CANVA_CLIENT_SECRET
    try:
        r = requests.post(
            "https://api.canva.com/rest/v1/oauth/token",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        j = r.json()
        access = j.get("access_token")
        if not access:
            return None
        CANVA_TOKEN_FILE.write_text(json.dumps({
            "access_token": access,
            "expires_at": time.time() + int(j.get("expires_in", 14400)) - 60,
            "refresh_token": j.get("refresh_token", CANVA_REFRESH_TOKEN),
        }))
        # If refresh_token rotated, the env one becomes stale — log file is now authoritative.
        return access
    except Exception:
        return None


def _canva_headers() -> dict:
    tok = _load_canva_token()
    return {"Authorization": f"Bearer {tok}"}

app = Flask(__name__)


def load_decisions() -> dict:
    if DECISIONS_FILE.exists():
        try:
            return json.loads(DECISIONS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_decisions(d: dict) -> None:
    DECISIONS_FILE.write_text(json.dumps(d, indent=2))


def parse_filename_meta(name: str) -> dict:
    """Parse SIIL naming convention into facets.
    Format: <Product> - <Gender> - <Model> - <Color> - <Aspect> - <Type> - <Scene>.<ext>
    e.g. 'Ostomy Wrap MIA - Women - Sofia - Cream - Vertical - Lifestyle - 01a_mirror_makeup.jpg'
    Falls back to empty dict for non-conforming names.
    """
    base = re.sub(r"\.(jpg|jpeg|png|webp)$", "", name, flags=re.I)
    parts = [p.strip() for p in base.split(" - ")]
    meta = {"product": "", "gender": "", "model": "", "color": "", "aspect": "", "type": "", "scene": ""}
    if len(parts) >= 1: meta["product"] = parts[0]
    if len(parts) >= 2: meta["gender"] = parts[1]
    if len(parts) >= 3: meta["model"] = parts[2]
    if len(parts) >= 4: meta["color"] = parts[3]
    if len(parts) >= 5: meta["aspect"] = parts[4]
    if len(parts) >= 6: meta["type"] = parts[5]
    if len(parts) >= 7: meta["scene"] = " - ".join(parts[6:])
    return meta


def list_batches() -> list[dict]:
    """Return a list of batches with parsed meta."""
    decisions = load_decisions()
    out = []
    for batch_dir in sorted(DATA_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not batch_dir.is_dir():
            continue
        images = []
        for f in sorted(batch_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if f.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
                continue
            rel = f"{batch_dir.name}/{f.name}"
            d = decisions.get(rel, {})
            meta = parse_filename_meta(f.name)
            images.append({
                "name": f.name,
                "rel_path": rel,
                "decision": d.get("decision", ""),
                "size": f.stat().st_size,
                "mtime": f.stat().st_mtime,
                **meta,
            })
        if images:
            out.append({"name": batch_dir.name, "images": images})
    return out


def collect_facets(batches: list[dict]) -> dict:
    """Return distinct values for each filterable facet."""
    facets = {"product": set(), "model": set(), "color": set(), "aspect": set(), "type": set()}
    for b in batches:
        for img in b["images"]:
            for k in facets:
                if img.get(k):
                    facets[k].add(img[k])
    return {k: sorted(v) for k, v in facets.items()}


@app.route("/")
def index():
    batches = list_batches()
    facets = collect_facets(batches)
    total = sum(len(b["images"]) for b in batches)
    decisions = load_decisions()
    n_keep = sum(1 for v in decisions.values() if v.get("decision") in ("keep", "uploaded"))
    n_delete = sum(1 for v in decisions.values() if v.get("decision") == "delete")
    n_undecided = total - n_keep - n_delete

    cards_html = []
    for b in batches:
        cards_html.append(f'<h2 class="batch-h">{escape(b["name"])} <span class="batch-count">{len(b["images"])} images</span></h2>')
        cards_html.append('<div class="batch-grid">')
        for img in b["images"]:
            d = img["decision"]
            cls = f' decided-{d}' if d else ""
            keep_active = "active" if d == "keep" else ""
            del_active = "active" if d == "delete" else ""
            uploaded_cls = " uploaded" if d == "uploaded" else ""
            canva_active = "active" if d == "uploaded" else ""
            asset_id = decisions.get(img['rel_path'], {}).get('asset_id', '')
            canva_btn_label = f"✓ In Canva" if d == "uploaded" else "↑ Canva"
            canva_btn_disabled = "disabled" if d == "uploaded" else ""
            asset_badge = f'<div class="asset-badge" title="Canva asset {escape(asset_id)}">→ Canva · {escape(asset_id[:10])}…</div>' if d == "uploaded" and asset_id else ""
            data_attrs = (
                f'data-product="{escape(img.get("product",""))}" '
                f'data-model="{escape(img.get("model",""))}" '
                f'data-color="{escape(img.get("color",""))}" '
                f'data-aspect="{escape(img.get("aspect",""))}" '
                f'data-type="{escape(img.get("type",""))}" '
                f'data-mtime="{int(img.get("mtime", 0))}" '
                f'data-search="{escape(img["name"].lower())}"'
            )
            cards_html.append(f'''
            <article class="card{cls}{uploaded_cls}" data-rel="{escape(img['rel_path'])}" {data_attrs}>
              <div class="image-wrap"><img loading="lazy" src="img/{escape(img['rel_path'])}" alt="{escape(img['name'])}"></div>
              <div class="card-body">
                <div class="filename" title="{escape(img['name'])}">{escape(img['name'])}</div>
                <div class="actions">
                  <button class="btn-canva {canva_active}" {canva_btn_disabled} onclick="uploadOne('{escape(img['rel_path'])}', this)">{canva_btn_label}</button>
                  <button class="btn-del {del_active}" onclick="decide('{escape(img['rel_path'])}','delete', this)">✗ Delete</button>
                </div>
                {asset_badge}
                <div class="card-status"></div>
              </div>
            </article>''')
        cards_html.append('</div>')

    body = "\n".join(cards_html) if batches else '<p class="empty">No images yet. Upload to data/&lt;batch&gt;/</p>'

    def _opts(values):
        return "\n".join(f'<option value="{escape(v)}">{escape(v)}</option>' for v in values)

    filters_html = f'''
<div class="filters">
  <input type="search" id="f-search" placeholder="Search filename / scene…" oninput="applyFilters()">
  <select id="f-product" onchange="applyFilters()">
    <option value="">All products</option>
    {_opts(facets["product"])}
  </select>
  <select id="f-model" onchange="applyFilters()">
    <option value="">All models</option>
    {_opts(facets["model"])}
  </select>
  <select id="f-aspect" onchange="applyFilters()">
    <option value="">All aspects</option>
    {_opts(facets["aspect"])}
  </select>
  <select id="f-type" onchange="applyFilters()">
    <option value="">All types</option>
    <option value="Studio">Studio</option>
    <option value="Lifestyle">Lifestyle</option>
  </select>
  <select id="f-color" onchange="applyFilters()">
    <option value="">All colors</option>
    {_opts(facets["color"])}
  </select>
  <select id="f-decision" onchange="applyFilters()">
    <option value="">All decisions</option>
    <option value="undecided">Undecided</option>
    <option value="uploaded">Uploaded ↑</option>
    <option value="delete">Marked delete</option>
  </select>
  <select id="f-sort" onchange="applyFilters()" title="Order">
    <option value="">Group by batch</option>
    <option value="newest">Newest first (flat)</option>
    <option value="oldest">Oldest first (flat)</option>
  </select>
  <button onclick="clearFilters()">Clear</button>
  <span id="filter-count" class="filter-count"></span>
</div>
'''

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><title>SIIL Gallery</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ --bg:#f4f3ee; --card:#fff; --text:#1a1815; --muted:#7a7367; --rule:#e3dfd6;
           --good:#3a7d5f; --bad:#b5755a; --primary:#3d5c7a; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--bg); font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; color:var(--text); }}
  .topbar {{ position:sticky; top:0; z-index:50; background:#fff; border-bottom:1px solid var(--rule);
            padding:14px 24px; display:flex; align-items:center; justify-content:space-between; box-shadow:0 1px 4px rgba(0,0,0,.04); }}
  .topbar h1 {{ font-size:18px; margin:0; font-weight:700; letter-spacing:-.01em; }}
  .topbar .meta {{ font-size:13px; color:var(--muted); }}
  .topbar .actions {{ display:flex; gap:8px; }}
  .topbar button {{ font-size:13px; padding:7px 16px; border-radius:6px; border:1px solid var(--rule); background:#fff; cursor:pointer; }}
  .topbar button.danger {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  .topbar button.canva {{ background:#7d2ae8; color:#fff; border-color:#7d2ae8; }}
  .modal-bg {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.5); z-index:200; align-items:center; justify-content:center; }}
  .modal-bg.show {{ display:flex; }}
  .modal {{ background:#fff; border-radius:10px; padding:24px; max-width:600px; width:90%; max-height:80vh; overflow:auto; }}
  .modal h3 {{ margin:0 0 12px; }}
  .modal pre {{ background:#f4f3ee; padding:12px; border-radius:6px; font-size:12px; white-space:pre-wrap; max-height:300px; overflow:auto; }}
  .modal button {{ margin-top:12px; padding:8px 16px; border-radius:6px; border:1px solid var(--rule); background:#fff; cursor:pointer; }}
  .topbar button:hover {{ filter: brightness(.97); }}
  .progress {{ display:flex; gap:18px; align-items:center; }}
  .progress span {{ font-size:13px; }}
  .progress .pill {{ padding:3px 10px; border-radius:12px; background:var(--rule); color:var(--text); font-weight:600; }}
  .progress .keep {{ background:#dbeae0; color:var(--good); }}
  .progress .del  {{ background:#f1dcd0; color:var(--bad); }}
  main {{ max-width:1400px; margin:24px auto; padding:0 20px; }}
  .batch-h {{ font-size:15px; font-weight:700; margin:32px 0 14px; color:var(--muted); text-transform:uppercase; letter-spacing:.06em; }}
  .batch-h .batch-count {{ font-weight:400; font-size:12px; margin-left:6px; }}
  .batch-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; }}
  .card {{ background:var(--card); border:1px solid var(--rule); border-radius:10px; overflow:hidden;
          display:flex; flex-direction:column; transition:opacity .08s, border-color .08s, box-shadow .08s, transform .08s; }}
  .card.decided-keep, .card.uploaded {{ border-color:#7d2ae8; box-shadow:0 0 0 2px rgba(125,42,232,.2); position:relative; }}
  .card.uploaded::before {{ content:"✓ in canva"; position:absolute; top:8px; right:8px; z-index:5; background:#7d2ae8; color:#fff; font-size:10px; font-weight:700; padding:3px 8px; border-radius:10px; letter-spacing:.04em; text-transform:uppercase; box-shadow:0 1px 4px rgba(0,0,0,.2); }}
  .asset-badge {{ font-size:10px; color:#7d2ae8; margin-top:6px; font-family:ui-monospace,Menlo,monospace; opacity:.8; }}
  .actions button:disabled {{ cursor:default; }}
  .card.decided-delete {{ border-color:var(--bad); opacity:.4; }}
  .card-status {{ font-size:11px; color:var(--muted); margin-top:6px; min-height:14px; }}
  .card-status.uploading {{ color:#7d2ae8; }}
  .card-status.ok {{ color:var(--good); }}
  .card-status.err {{ color:var(--bad); }}
  .image-wrap {{ background:#000; aspect-ratio:9/16; display:flex; align-items:center; justify-content:center; }}
  .image-wrap img {{ display:block; width:100%; height:100%; object-fit:contain; cursor:zoom-in; }}
  .card-body {{ padding:10px 12px; }}
  .filename {{ font-size:11px; color:var(--muted); margin-bottom:8px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .actions {{ display:flex; gap:6px; }}
  .actions button {{ flex:1; padding:8px; font-size:13px; font-weight:600; border-radius:6px; border:1px solid var(--rule); background:#fff; cursor:pointer; transition:all .12s; }}
  .actions .btn-canva:hover {{ background:#f3eafd; border-color:#7d2ae8; color:#7d2ae8; }}
  .actions .btn-canva.active {{ background:#7d2ae8; color:#fff; border-color:#7d2ae8; }}
  .actions .btn-del:hover {{ background:#f7e7dd; border-color:var(--bad); color:var(--bad); }}
  .actions .btn-del.active {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  /* Lightbox */
  .lightbox {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,.95); z-index:100; }}
  .lightbox.show {{ display:flex; align-items:center; justify-content:center; }}
  .lb-content {{ display:flex; flex-direction:column; align-items:center; gap:14px; max-width:96vw; max-height:96vh; }}
  .lb-content img {{ max-width:96vw; max-height:78vh; object-fit:contain; border-radius:6px; box-shadow:0 4px 30px rgba(0,0,0,.4); }}
  .lb-meta {{ color:#fff; font-size:12px; text-align:center; opacity:.85; }}
  .lb-meta .lb-name {{ font-family:ui-monospace,Menlo,monospace; font-size:11px; max-width:80vw; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .lb-meta .lb-counter {{ font-size:11px; opacity:.7; margin-top:2px; }}
  .lb-actions {{ display:flex; gap:10px; }}
  .lb-actions button {{ padding:10px 20px; font-size:14px; font-weight:600; border-radius:6px; border:0; cursor:pointer; display:flex; align-items:center; gap:8px; }}
  .lb-actions kbd {{ font-size:10px; opacity:.65; background:rgba(255,255,255,.15); padding:2px 5px; border-radius:3px; font-family:ui-monospace,monospace; }}
  .lb-canva {{ background:#7d2ae8; color:#fff; }}
  .lb-canva:hover {{ background:#6520c0; }}
  .lb-canva.uploaded {{ background:#3a7d5f; cursor:default; }}
  .lb-canva.uploaded:hover {{ background:#3a7d5f; }}
  .lb-delete {{ background:#b5755a; color:#fff; }}
  .lb-delete:hover {{ background:#945e44; }}
  .lb-hint {{ color:#fff; opacity:.5; font-size:11px; }}
  .lb-close, .lb-nav {{ position:fixed; background:rgba(255,255,255,.1); border:0; color:#fff; font-size:24px; cursor:pointer; border-radius:50%; display:flex; align-items:center; justify-content:center; transition:background .12s; }}
  .lb-close {{ top:20px; right:20px; width:44px; height:44px; }}
  .lb-nav {{ top:50%; transform:translateY(-50%); width:50px; height:50px; }}
  .lb-prev {{ left:20px; }}
  .lb-next {{ right:20px; }}
  .lb-close:hover, .lb-nav:hover {{ background:rgba(255,255,255,.2); }}
  .empty {{ text-align:center; padding:60px 20px; color:var(--muted); }}
  .filters {{ position:sticky; top:var(--topbar-h, 64px); z-index:40; background:#fff; border-bottom:1px solid var(--rule); padding:10px 24px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .filters input, .filters select {{ font-size:13px; padding:7px 12px; border:1px solid var(--rule); border-radius:6px; background:#fff; min-width:140px; }}
  .filters input {{ flex:1; min-width:200px; max-width:340px; }}
  .filters button {{ font-size:13px; padding:7px 14px; border:1px solid var(--rule); border-radius:6px; background:#fff; cursor:pointer; }}
  .filters button:hover {{ background:#f4f3ee; }}
  .filter-count {{ font-size:12px; color:var(--muted); margin-left:auto; }}
  /* Back-to-top floating button */
  #back-to-top {{ position:fixed; bottom:24px; right:24px; z-index:150;
    width:48px; height:48px; border-radius:24px; border:none;
    background:var(--primary); color:#fff; font-size:22px; cursor:pointer;
    box-shadow:0 4px 14px rgba(0,0,0,.18);
    opacity:0; pointer-events:none; transform:translateY(8px);
    transition:opacity .18s ease, transform .18s ease, background .15s ease; }}
  #back-to-top.visible {{ opacity:1; pointer-events:auto; transform:translateY(0); }}
  #back-to-top:hover {{ background:#2a4259; }}
  /* Flat-sort grid (used when "Newest first" / "Oldest first" sort is active) */
  #flat-grid {{ display:none; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; margin-top:8px; }}
  body.sort-flat #flat-grid {{ display:grid; }}
  body.sort-flat .batch-h, body.sort-flat .batch-grid {{ display:none !important; }}
</style>
</head><body>
<div class="topbar">
  <h1>SIIL Gallery</h1>
  <div class="progress">
    <span class="pill keep" id="n-keep">{n_keep} keep</span>
    <span class="pill del" id="n-del">{n_delete} delete</span>
    <span class="pill" id="n-undecided">{n_undecided} undecided</span>
    <span style="font-size:12px;color:var(--muted)">/ {total} total</span>
  </div>
  <div class="actions">
    <button onclick="window.location.reload()">Refresh</button>
    <button onclick="undoLast()" title="Undo last action (Ctrl+Z)">↶ Undo</button>
    <button id="canva-reconnect-btn" onclick="canvaReconnect()" title="Re-authorize Canva (only needed if upload says auth failed)" style="display:none;">↻ Reconnect Canva</button>
    <button class="canva" onclick="bulkUpload()">↑ Bulk upload visible</button>
    <button class="danger" onclick="applyDeletes()">Apply deletes</button>
  </div>
</div>
<div id="canva-modal" class="modal-bg" onclick="if(event.target===this)closeCanva()">
  <div class="modal">
    <h3 id="canva-title">Upload to Canva</h3>
    <div id="canva-status">Uploading…</div>
    <pre id="canva-log"></pre>
    <button onclick="closeCanva()">Close</button>
  </div>
</div>
{filters_html}
<main>
{body}
<div id="flat-grid"></div>
</main>
<button id="back-to-top" title="Back to top" onclick="scrollToTop()">↑</button>
<div id="lightbox" class="lightbox">
  <button class="lb-close" onclick="closeLightbox()" title="Close (Esc)">&times;</button>
  <button class="lb-nav lb-prev" onclick="navLightbox(-1)" title="Previous (←)">&#10094;</button>
  <button class="lb-nav lb-next" onclick="navLightbox(1)" title="Next (→)">&#10095;</button>
  <div class="lb-content">
    <img id="lb-img" src="">
    <div class="lb-meta">
      <div class="lb-name" id="lb-name"></div>
      <div class="lb-counter" id="lb-counter"></div>
    </div>
    <div class="lb-actions">
      <button class="lb-canva" id="lb-canva-btn" onclick="lightboxAction('canva')">&uarr; Upload to Canva  <kbd>Enter</kbd></button>
      <button class="lb-delete" onclick="lightboxAction('delete')">&times; Delete  <kbd>Del</kbd></button>
    </div>
    <div class="lb-hint">← → navigate · Esc close</div>
  </div>
</div>
<script>
function decide(rel, action, btn) {{
  const card = btn.closest('.card');
  if (action === 'delete') {{
    // INSTANT — remove from DOM immediately, server fires in background
    card.remove();
    applyFilters();
    fetch('delete_now', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel: rel}})
    }}).then(r => r.json()).then(d => {{
      if (d.ok) pushAction({{kind: 'delete_now', rel, batch_id: d.batch_id}});
    }});
    return;
  }}
  // Other actions (keep) still go through decide endpoint
  const prevDecision = card.classList.contains('decided-keep') ? 'keep'
    : card.classList.contains('uploaded') ? 'uploaded' : '';
  const current = card.classList.contains('decided-' + action);
  const newDecision = current ? '' : action;
  fetch('decide', {{
    method: 'POST', headers: {{'Content-Type':'application/json'}},
    body: JSON.stringify({{rel: rel, decision: newDecision}})
  }}).then(r => r.json()).then(d => {{
    card.classList.remove('decided-keep');
    card.querySelectorAll('.actions button').forEach(b => b.classList.remove('active'));
    if (d.decision && d.decision !== 'delete') {{
      card.classList.add('decided-' + d.decision);
      const b2 = card.querySelector('.btn-canva');
      if (b2) b2.classList.add('active');
    }}
    document.getElementById('n-keep').textContent = d.counts.keep + ' keep';
    document.getElementById('n-del').textContent = d.counts.delete + ' delete';
    document.getElementById('n-undecided').textContent = d.counts.undecided + ' undecided';
    if (newDecision) pushAction({{rel, kind: newDecision, prevDecision}});
  }});
}}

function applyDeletes() {{
  if (!confirm('Move all "delete"-marked images to trash? You can undo with the Undo button (or Ctrl+Z).')) return;
  fetch('apply_deletes', {{method: 'POST'}})
    .then(r => r.json())
    .then(d => {{
      if (d.moved > 0) {{
        pushAction({{kind: 'apply_deletes', batch_id: d.batch_id, count: d.moved}});
        alert('Moved ' + d.moved + ' files to trash. Undo with Ctrl+Z to restore.');
      }} else {{
        alert('No files marked for deletion.');
      }}
      window.location.reload();
    }});
}}

function undoApplyDeletes() {{
  fetch('undo_apply_deletes', {{method: 'POST'}})
    .then(r => r.json())
    .then(d => {{
      if (d.ok) {{
        alert('Restored ' + d.restored + ' files from trash.');
        window.location.reload();
      }} else {{
        alert('Undo failed: ' + (d.error || 'unknown'));
      }}
    }});
}}

function applyFilters() {{
  const q = (document.getElementById('f-search').value || '').toLowerCase();
  const fp = document.getElementById('f-product').value;
  const fm = document.getElementById('f-model').value;
  const fa = document.getElementById('f-aspect').value;
  const ft = document.getElementById('f-type').value;
  const fc = document.getElementById('f-color').value;
  const fd = document.getElementById('f-decision').value;
  const fs = (document.getElementById('f-sort') || {{}}).value || '';
  let shown = 0, total = 0;
  document.querySelectorAll('.card').forEach(c => {{
    total++;
    const okSearch = !q || (c.dataset.search || '').includes(q);
    const okProd = !fp || c.dataset.product === fp;
    const okModel = !fm || c.dataset.model === fm;
    const okAsp = !fa || c.dataset.aspect === fa;
    const okType = !ft || c.dataset.type === ft;
    const okColor = !fc || c.dataset.color === fc;
    let okDec = true;
    if (fd === 'undecided') {{
      okDec = !c.classList.contains('decided-keep') && !c.classList.contains('decided-delete') && !c.classList.contains('uploaded');
    }} else if (fd === 'uploaded') {{
      okDec = c.classList.contains('uploaded');
    }} else if (fd === 'delete') {{
      okDec = c.classList.contains('decided-delete');
    }}
    const show = okSearch && okProd && okModel && okAsp && okType && okColor && okDec;
    c.style.display = show ? '' : 'none';
    if (show) shown++;
  }});
  // Hide batch headers with zero visible cards
  document.querySelectorAll('.batch-h').forEach(h => {{
    let n = h.nextElementSibling;
    let visible = 0;
    while (n && !n.classList.contains('batch-h')) {{
      if (n.classList.contains('card') && n.style.display !== 'none') visible++;
      else if (n.classList.contains('batch-grid')) {{
        n.querySelectorAll('.card').forEach(c => {{ if (c.style.display !== 'none') visible++; }});
      }}
      n = n.nextElementSibling;
    }}
    h.style.display = visible === 0 ? 'none' : '';
  }});
  // Apply flat sort (newest/oldest) — moves visible cards into #flat-grid sorted by mtime
  applySort(fs);
  document.getElementById('filter-count').textContent = `Showing ${{shown}} / ${{total}}`;
}}

// ── Sort: flat-grid mode (newest/oldest first across all batches) ──
function applySort(mode) {{
  const flat = document.getElementById('flat-grid');
  if (!flat) return;
  if (!mode) {{
    // Restore: move every card back to its original batch grid
    document.body.classList.remove('sort-flat');
    Array.from(flat.children).forEach(card => {{
      const home = card.dataset.homeId;
      if (home) {{
        const grid = document.getElementById(home);
        if (grid) grid.appendChild(card);
      }}
    }});
    return;
  }}
  // Tag each batch-grid with a stable id so we can return cards home
  document.querySelectorAll('.batch-grid').forEach((g, i) => {{
    if (!g.id) g.id = 'bg-' + i;
  }});
  // Collect all currently visible cards (style.display !== 'none')
  const cards = Array.from(document.querySelectorAll('.card')).filter(c => c.style.display !== 'none');
  cards.forEach(c => {{
    if (!c.dataset.homeId) {{
      const parent = c.parentElement;
      if (parent && parent.classList.contains('batch-grid')) c.dataset.homeId = parent.id;
    }}
  }});
  cards.sort((a, b) => {{
    const ma = +a.dataset.mtime || 0;
    const mb = +b.dataset.mtime || 0;
    return mode === 'newest' ? (mb - ma) : (ma - mb);
  }});
  // Move all visible cards into flat-grid in sorted order
  cards.forEach(c => flat.appendChild(c));
  document.body.classList.add('sort-flat');
}}

function clearFilters() {{
  ['f-search','f-product','f-model','f-aspect','f-type','f-color','f-decision','f-sort'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.value = '';
  }});
  applyFilters();
}}

function uploadOne(rel, btn) {{
  const card = btn.closest('.card');
  const status = card.querySelector('.card-status');
  status.className = 'card-status uploading';
  status.textContent = 'Uploading to Canva…';
  btn.disabled = true;
  fetch('upload_canva_one', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rel: rel}})
  }})
  .then(r => r.json())
  .then(d => {{
    btn.disabled = false;
    if (d.ok) {{
      status.className = 'card-status ok';
      status.textContent = '✓ Uploaded · ' + (d.asset_id||'').slice(0,12) + '…';
      card.classList.add('uploaded');
      btn.classList.add('active');
      btn.textContent = '✓ In Canva';
      btn.disabled = true;
    }} else {{
      status.className = 'card-status err';
      status.textContent = '✗ ' + (d.error || 'Upload failed');
    }}
  }})
  .catch(e => {{
    btn.disabled = false;
    status.className = 'card-status err';
    status.textContent = '✗ ' + e.toString();
  }});
}}

function bulkUpload() {{
  // Collect all currently-visible cards that aren't already uploaded or deleted
  const rels = [];
  document.querySelectorAll('.card').forEach(c => {{
    if (c.style.display === 'none') return;
    if (c.classList.contains('uploaded')) return;
    if (c.classList.contains('decided-delete')) return;
    rels.push(c.dataset.rel);
  }});
  if (rels.length === 0) {{
    alert('Nothing to upload. (Cards may all be already uploaded or marked delete, or filtered out.)');
    return;
  }}
  if (!confirm('Upload ' + rels.length + ' visible images to Canva folder? This may take ~5-10s per image.')) return;
  document.getElementById('canva-modal').classList.add('show');
  document.getElementById('canva-status').textContent = 'Bulk uploading ' + rels.length + ' images…';
  document.getElementById('canva-log').textContent = '';
  fetch('upload_canva_bulk', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rels: rels}})
  }})
    .then(r => r.json())
    .then(d => {{
      document.getElementById('canva-status').textContent = d.summary || ('Uploaded ' + (d.uploaded||0) + ' / ' + (d.total||0));
      document.getElementById('canva-log').textContent = (d.log || []).join('\\n') + (d.error ? '\\n\\nERROR: ' + d.error : '');
      // Mark uploaded cards in UI
      (d.uploaded_rels || []).forEach(rel => {{
        const card = document.querySelector(`.card[data-rel="${{rel.replace(/"/g, '\\\\"')}}"]`);
        if (card) {{
          card.classList.add('uploaded');
          const btn = card.querySelector('.btn-canva');
          if (btn) {{ btn.classList.add('active'); btn.textContent = '✓ In Canva'; btn.disabled = true; }}
        }}
      }});
    }})
    .catch(e => {{
      document.getElementById('canva-status').textContent = 'Request failed';
      document.getElementById('canva-log').textContent = e.toString();
    }});
}}
function closeCanva() {{ document.getElementById('canva-modal').classList.remove('show'); }}

// ── Action history for undo ──
const actionHistory = [];  // {{rel, kind, prevDecision, prevAssetId}}

function pushAction(action) {{
  actionHistory.push(action);
  if (actionHistory.length > 50) actionHistory.shift();
  updateUndoButton();
}}

function updateUndoButton() {{
  // (placeholder — could show count etc.)
}}

function undoLast() {{
  if (actionHistory.length === 0) {{
    return;  // nothing to undo
  }}
  const action = actionHistory.pop();
  const card = document.querySelector(`.card[data-rel="${{action.rel.replace(/"/g, '\\\\"')}}"]`);
  if (!card) return;

  if (action.kind === 'apply_deletes' || action.kind === 'delete_now') {{
    // Restore files from trash (the most recent batch)
    undoApplyDeletes();
    return;
  }}
  if (action.kind === 'canva') {{
    // Reverse a Canva upload: delete the asset from Canva, clear decision
    fetch('canva_undo', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel: action.rel, asset_id: action.prevAssetId || ''}})
    }}).then(r => r.json()).then(d => {{
      card.classList.remove('uploaded');
      const cardBtn = card.querySelector('.btn-canva');
      if (cardBtn) {{ cardBtn.classList.remove('active'); cardBtn.textContent = '↑ Canva'; cardBtn.disabled = false; }}
      const status = card.querySelector('.card-status');
      if (status) {{ status.className = 'card-status'; status.textContent = ''; }}
      // Update lightbox if open and showing this card
      if (lbCurrentCard === card) openLightbox(card);
    }});
  }} else if (action.kind === 'delete' || action.kind === 'keep') {{
    // Restore the previous decision (or clear)
    fetch('decide', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel: action.rel, decision: action.prevDecision || ''}})
    }}).then(r => r.json()).then(d => {{
      card.classList.remove('decided-keep', 'decided-delete', 'uploaded');
      card.querySelectorAll('.actions button').forEach(b => b.classList.remove('active'));
      if (action.prevDecision) {{
        card.classList.add('decided-' + action.prevDecision);
        const sel = action.prevDecision === 'delete' ? '.btn-del' : '.btn-canva';
        const b = card.querySelector(sel);
        if (b) b.classList.add('active');
      }}
      if (lbCurrentCard === card) openLightbox(card);
    }});
  }}
}}


// ── Lightbox with navigation, actions, keyboard shortcuts ──
let lbCurrentCard = null;

function getVisibleCards() {{
  return Array.from(document.querySelectorAll('.card')).filter(c => c.style.display !== 'none');
}}

function openLightbox(card) {{
  if (!card) return;
  lbCurrentCard = card;
  const img = card.querySelector('.image-wrap img');
  const filename = card.querySelector('.filename')?.textContent || '';
  document.getElementById('lb-img').src = img.src;
  document.getElementById('lb-name').textContent = filename;
  // counter
  const visible = getVisibleCards();
  const idx = visible.indexOf(card);
  document.getElementById('lb-counter').textContent = `${{idx + 1}} / ${{visible.length}}`;
  // canva button state
  const canvaBtn = document.getElementById('lb-canva-btn');
  if (card.classList.contains('uploaded')) {{
    canvaBtn.classList.add('uploaded');
    canvaBtn.innerHTML = '&#10003; In Canva';
    canvaBtn.disabled = true;
  }} else {{
    canvaBtn.classList.remove('uploaded');
    canvaBtn.innerHTML = '&uarr; Upload to Canva  <kbd>Enter</kbd>';
    canvaBtn.disabled = false;
  }}
  document.getElementById('lightbox').classList.add('show');
}}

function closeLightbox() {{
  document.getElementById('lightbox').classList.remove('show');
  lbCurrentCard = null;
}}

function navLightbox(dir) {{
  if (!lbCurrentCard) return;
  const visible = getVisibleCards();
  const idx = visible.indexOf(lbCurrentCard);
  if (idx < 0) return;
  const next = visible[(idx + dir + visible.length) % visible.length];
  if (next) {{
    openLightbox(next);
    // smoothly scroll the card into view in the background
    next.scrollIntoView({{behavior: 'smooth', block: 'center'}});
  }}
}}

function lightboxAction(kind) {{
  if (!lbCurrentCard) return;
  const rel = lbCurrentCard.dataset.rel;
  const card = lbCurrentCard;
  const prevDecision = card.classList.contains('uploaded') ? 'uploaded'
    : card.classList.contains('decided-delete') ? 'delete'
    : card.classList.contains('decided-keep') ? 'keep' : '';

  if (kind === 'canva') {{
    if (card.classList.contains('uploaded')) return;
    const canvaBtn = document.getElementById('lb-canva-btn');
    canvaBtn.disabled = true;
    canvaBtn.innerHTML = 'Uploading…';
    fetch('upload_canva_one', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel}})
    }}).then(r => r.json()).then(d => {{
      if (d.ok) {{
        card.classList.add('uploaded');
        const cardBtn = card.querySelector('.btn-canva');
        if (cardBtn) {{ cardBtn.classList.add('active'); cardBtn.textContent = '✓ In Canva'; cardBtn.disabled = true; }}
        canvaBtn.classList.add('uploaded');
        canvaBtn.innerHTML = '&#10003; In Canva';
        pushAction({{rel, kind: 'canva', prevDecision, prevAssetId: d.asset_id}});
        setTimeout(() => navLightbox(1), 300);
      }} else {{
        canvaBtn.disabled = false;
        canvaBtn.innerHTML = '&uarr; Upload to Canva  <kbd>Enter</kbd>';
        alert('Upload failed: ' + (d.error || 'unknown'));
      }}
    }});
  }} else if (kind === 'delete') {{
    // INSTANT — remove from DOM, nav to next, server fires in background
    navLightbox(1);
    card.remove();
    applyFilters();
    fetch('delete_now', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel}})
    }}).then(r => r.json()).then(d => {{
      if (d.ok) pushAction({{kind: 'delete_now', rel, batch_id: d.batch_id}});
    }});
  }}
}}

document.addEventListener('click', (e) => {{
  if (e.target.tagName === 'IMG' && e.target.closest('.image-wrap')) {{
    const card = e.target.closest('.card');
    openLightbox(card);
  }}
}});

document.addEventListener('keydown', (e) => {{
  // Global Ctrl+Z / Cmd+Z = undo (works whether lightbox open or not)
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {{
    e.preventDefault();
    undoLast();
    return;
  }}
  const lb = document.getElementById('lightbox');
  if (!lb.classList.contains('show')) return;
  // Skip if user is typing in a search/text input
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  if (e.key === 'Escape') {{ e.preventDefault(); closeLightbox(); }}
  else if (e.key === 'ArrowRight') {{ e.preventDefault(); navLightbox(1); }}
  else if (e.key === 'ArrowLeft') {{ e.preventDefault(); navLightbox(-1); }}
  else if (e.key === 'Enter') {{ e.preventDefault(); lightboxAction('canva'); }}
  else if (e.key === 'Delete' || e.key === 'Backspace') {{ e.preventDefault(); lightboxAction('delete'); }}
}});

// Click outside the content to close
document.getElementById('lightbox').addEventListener('click', (e) => {{
  if (e.target.id === 'lightbox') closeLightbox();
}});

// ── Sticky topbar height — recompute so .filters never hides under topbar ──
function setTopbarHeight() {{
  const tb = document.querySelector('.topbar');
  if (!tb) return;
  document.documentElement.style.setProperty('--topbar-h', tb.offsetHeight + 'px');
}}
window.addEventListener('load', setTopbarHeight);
window.addEventListener('resize', setTopbarHeight);

// ── Back-to-top floating button ──
window.addEventListener('scroll', () => {{
  const btn = document.getElementById('back-to-top');
  if (btn) btn.classList.toggle('visible', window.scrollY > 400);
}});
function scrollToTop() {{
  window.scrollTo({{top: 0, behavior: 'smooth'}});
}}

// ── Canva auth status check (show "Reconnect Canva" button if revoked/expired) ──
function canvaReconnect() {{
  // Open OAuth flow in popup; reload main page when popup closes
  const w = window.open('canva/start', 'canva-oauth', 'width=520,height=700');
  const timer = setInterval(() => {{
    if (!w || w.closed) {{ clearInterval(timer); window.location.reload(); }}
  }}, 800);
}}
function checkCanvaAuth() {{
  fetch('canva/status').then(r => r.json()).then(d => {{
    const btn = document.getElementById('canva-reconnect-btn');
    if (!btn) return;
    btn.style.display = (d.ok && !d.needs_auth) ? 'none' : 'inline-block';
    if (!d.ok || d.needs_auth) btn.style.background = '#b5755a', btn.style.color = '#fff', btn.style.borderColor = '#b5755a';
  }}).catch(() => {{}});
}}
window.addEventListener('load', checkCanvaAuth);
</script>
</body></html>"""
    resp = app.make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


@app.route("/img/<path:rel>")
def serve_img(rel: str):
    rel = rel.replace("..", "")
    p = (DATA_DIR / rel).resolve()
    if not str(p).startswith(str(DATA_DIR)) or not p.exists():
        abort(404)
    return send_file(p)


@app.route("/decide", methods=["POST"])
def decide():
    data = request.get_json() or {}
    rel = data.get("rel", "").replace("..", "")
    decision = data.get("decision", "")
    if decision not in ("keep", "delete", ""):
        abort(400)
    decisions = load_decisions()
    if decision:
        decisions[rel] = {"decision": decision, "ts": time.time()}
    else:
        decisions.pop(rel, None)
    save_decisions(decisions)
    counts = {"keep": 0, "delete": 0}
    for v in decisions.values():
        if v.get("decision") in counts:
            counts[v["decision"]] += 1
    total = 0
    for batch_dir in DATA_DIR.iterdir():
        if batch_dir.is_dir():
            total += sum(1 for f in batch_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    counts["undecided"] = total - counts["keep"] - counts["delete"]
    return jsonify({"decision": decision, "counts": counts})


APPLY_DELETES_LOG = DATA_DIR.parent / "apply_deletes_log.json"


def _load_apply_log() -> list:
    if APPLY_DELETES_LOG.exists():
        try:
            return json.loads(APPLY_DELETES_LOG.read_text())
        except Exception:
            return []
    return []


def _save_apply_log(entries: list) -> None:
    APPLY_DELETES_LOG.write_text(json.dumps(entries, indent=2))


@app.route("/delete_now", methods=["POST"])
def delete_now():
    """Delete a single image immediately (move to trash) — no need for Apply deletes."""
    data = request.get_json() or {}
    rel = data.get("rel", "").replace("..", "")
    src = (DATA_DIR / rel).resolve()
    if not str(src).startswith(str(DATA_DIR)) or not src.exists():
        return jsonify({"ok": False, "error": "file not found"}), 404
    batch_id = time.strftime("%Y%m%d-%H%M%S-%f")
    dst = TRASH_DIR / f"{batch_id}_{rel.replace('/', '__')}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    # Clear any decision entry
    decisions = load_decisions()
    decisions.pop(rel, None)
    save_decisions(decisions)
    # Record in apply log so undo works the same way
    log = _load_apply_log()
    log.append({"batch_id": batch_id, "ts": time.time(), "moves": [{"rel": rel, "trash_path": str(dst)}]})
    log = log[-50:]
    _save_apply_log(log)
    return jsonify({"ok": True, "batch_id": batch_id, "rel": rel})


@app.route("/apply_deletes", methods=["POST"])
def apply_deletes():
    decisions = load_decisions()
    batch_id = time.strftime("%Y%m%d-%H%M%S")
    moves = []  # list of {rel, trash_path}
    for rel, d in list(decisions.items()):
        if d.get("decision") != "delete":
            continue
        src = (DATA_DIR / rel).resolve()
        if not str(src).startswith(str(DATA_DIR)) or not src.exists():
            continue
        dst = TRASH_DIR / f"{batch_id}_{rel.replace('/', '__')}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        moves.append({"rel": rel, "trash_path": str(dst)})
        decisions.pop(rel, None)
    save_decisions(decisions)

    # Record this batch so we can undo it
    if moves:
        log = _load_apply_log()
        log.append({"batch_id": batch_id, "ts": time.time(), "moves": moves})
        # keep only last 20 batches
        log = log[-20:]
        _save_apply_log(log)

    return jsonify({"moved": len(moves), "batch_id": batch_id})


@app.route("/undo_apply_deletes", methods=["POST"])
def undo_apply_deletes():
    """Restore the last apply_deletes batch from trash back to data/."""
    log = _load_apply_log()
    if not log:
        return jsonify({"ok": False, "error": "No apply_deletes batches to undo"}), 400
    last = log.pop()
    restored = 0
    failed = []
    for mv in last.get("moves", []):
        rel = mv["rel"]
        trash_path = pathlib.Path(mv["trash_path"])
        target = (DATA_DIR / rel).resolve()
        if not str(target).startswith(str(DATA_DIR)):
            failed.append(rel); continue
        if not trash_path.exists():
            failed.append(rel); continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(trash_path), str(target))
        restored += 1
    _save_apply_log(log)
    return jsonify({"ok": True, "restored": restored, "failed": failed, "batch_id": last["batch_id"]})


def load_canva_log() -> dict:
    if CANVA_LOG.exists():
        try:
            return json.loads(CANVA_LOG.read_text())
        except Exception:
            return {}
    return {}


def save_canva_log(d: dict) -> None:
    CANVA_LOG.write_text(json.dumps(d, indent=2))


def _upload_one_to_canva(rel: str, _retry: bool = False) -> tuple[bool, str, str]:
    """Returns (ok, asset_id_or_msg, status_str). Auto-refreshes token on 401."""
    if not _load_canva_token():
        return False, "Canva not configured (no token)", "no-token"
    canva_log = load_canva_log()
    if rel in canva_log and canva_log[rel].get("asset_id"):
        return True, canva_log[rel]["asset_id"], "already"

    src = (DATA_DIR / rel).resolve()
    if not str(src).startswith(str(DATA_DIR)) or not src.exists():
        return False, "file not found", "missing"

    url = f"{PUBLIC_BASE_URL.rstrip('/')}/img/{urllib.parse.quote(rel)}"
    fname = pathlib.Path(rel).name
    headers = _canva_headers()

    try:
        r = requests.post(
            "https://api.canva.com/rest/v1/url-asset-uploads",
            headers={**headers, "Content-Type": "application/json"},
            json={"url": url, "name": fname},
            timeout=60,
        )
        if r.status_code == 401 and not _retry:
            if _refresh_canva_token():
                return _upload_one_to_canva(rel, _retry=True)
            return False, "auth failed and could not refresh", "auth"
        if r.status_code not in (200, 201, 202):
            return False, f"HTTP {r.status_code}: {r.text[:160]}", "err"
        job_id = r.json().get("job", {}).get("id")
        if not job_id:
            return False, "no job id", "err"

        asset_id = None
        for _ in range(30):
            pr = requests.get(
                f"https://api.canva.com/rest/v1/url-asset-uploads/{job_id}",
                headers=headers, timeout=30,
            )
            if pr.status_code == 200:
                pjob = pr.json().get("job", {})
                if pjob.get("status") == "success":
                    asset_id = pjob.get("asset", {}).get("id")
                    break
                if pjob.get("status") == "failed":
                    return False, f"job failed: {pjob.get('error', {}).get('message', 'unknown')}", "err"
            time.sleep(2)

        if not asset_id:
            return False, "upload timeout", "err"

        if CANVA_FOLDER_ID:
            # Canva API: move asset (which lives in user's "uploads" virtual folder)
            # to the target folder. Endpoint: POST /v1/folders/move-folder-item
            # Try both known shapes — Canva has rotated the spec a few times.
            move_attempts = [
                # Newest: POST /v1/folders/move
                ("https://api.canva.com/rest/v1/folders/move",
                 {"to_folder_id": CANVA_FOLDER_ID, "item_id": asset_id}),
                # Older: POST /v1/folders/move-folder-item
                ("https://api.canva.com/rest/v1/folders/move-folder-item",
                 {"to_folder_id": CANVA_FOLDER_ID, "item_id": asset_id}),
                # Alternate: POST /v1/folders/{id}/items with flat body
                (f"https://api.canva.com/rest/v1/folders/{CANVA_FOLDER_ID}/items",
                 {"type": "asset", "asset_id": asset_id}),
            ]
            folder_status = "move-not-attempted"
            for ep, body_json in move_attempts:
                mr = requests.post(ep, headers={**headers, "Content-Type": "application/json"},
                                   json=body_json, timeout=30)
                if mr.status_code in (200, 201, 204):
                    folder_status = f"ok ({ep.rsplit('/', 1)[-1]})"
                    break
                folder_status = f"{mr.status_code} {mr.text[:120]}"
        else:
            folder_status = "no-folder"

        canva_log[rel] = {"asset_id": asset_id, "ts": time.time(), "folder": folder_status, "folder_id": CANVA_FOLDER_ID}
        save_canva_log(canva_log)
        # Mark as uploaded in decisions
        decisions = load_decisions()
        decisions[rel] = {"decision": "uploaded", "ts": time.time(), "asset_id": asset_id}
        save_decisions(decisions)
        return True, asset_id, f"uploaded · folder:{folder_status}"
    except Exception as e:
        return False, str(e)[:160], "err"


@app.route("/canva_undo", methods=["POST"])
def canva_undo():
    """Undo a Canva upload: delete the asset from Canva and clear the local upload record."""
    data = request.get_json() or {}
    rel = data.get("rel", "").replace("..", "")
    asset_id = data.get("asset_id", "")

    # Try to find the asset_id in our log if not supplied
    canva_log = load_canva_log()
    if not asset_id:
        asset_id = canva_log.get(rel, {}).get("asset_id", "")

    canva_deleted = False
    if asset_id:
        try:
            r = requests.delete(
                f"https://api.canva.com/rest/v1/assets/{asset_id}",
                headers=_canva_headers(),
                timeout=30,
            )
            if r.status_code == 401:
                if _refresh_canva_token():
                    r = requests.delete(
                        f"https://api.canva.com/rest/v1/assets/{asset_id}",
                        headers=_canva_headers(),
                        timeout=30,
                    )
            canva_deleted = r.status_code in (200, 204)
        except Exception:
            pass

    # Clear local records
    canva_log.pop(rel, None)
    save_canva_log(canva_log)
    decisions = load_decisions()
    decisions.pop(rel, None)
    save_decisions(decisions)
    return jsonify({"ok": True, "canva_deleted": canva_deleted, "asset_id": asset_id})


@app.route("/upload_canva_one", methods=["POST"])
def upload_canva_one():
    data = request.get_json() or {}
    rel = data.get("rel", "").replace("..", "")
    ok, msg, _ = _upload_one_to_canva(rel)
    if ok:
        return jsonify({"ok": True, "asset_id": msg})
    return jsonify({"ok": False, "error": msg}), 400


@app.route("/upload_canva_bulk", methods=["POST"])
def upload_canva_bulk():
    """Bulk upload a list of rel_paths to Canva (sequential, with progress log)."""
    data = request.get_json() or {}
    rels = [r.replace("..", "") for r in data.get("rels", [])]
    if not rels:
        return jsonify({"summary": "No images supplied.", "log": [], "uploaded": 0, "total": 0})
    log: list[str] = []
    uploaded = 0
    skipped = 0
    failed = 0
    uploaded_rels: list[str] = []
    for rel in rels:
        ok, msg, status = _upload_one_to_canva(rel)
        if ok:
            if status == "already":
                log.append(f"⏭  {rel}: already uploaded ({msg})")
                skipped += 1
            else:
                log.append(f"✓  {rel} → {msg}")
                uploaded += 1
                uploaded_rels.append(rel)
        else:
            log.append(f"✗  {rel}: {msg}")
            failed += 1
    return jsonify({
        "summary": f"Uploaded {uploaded}, skipped {skipped} (already), failed {failed}, total {len(rels)}",
        "log": log,
        "uploaded": uploaded, "skipped": skipped, "failed": failed, "total": len(rels),
        "uploaded_rels": uploaded_rels,
    })


@app.route("/upload_canva", methods=["POST"])
def upload_canva():
    """Upload all 'keep'-marked images to Canva via the REST API.

    Uses upload-asset-from-url with our public image URLs (the same ones
    the front-end shows). Skips images already uploaded (logged in
    canva_uploads.json by relative path).
    """
    if not CANVA_API_TOKEN:
        return jsonify({
            "error": "CANVA_API_TOKEN not set on server. Add it to /home/siil_ostomy/image-review/.env then restart.",
            "summary": "Not configured",
        }), 400

    decisions = load_decisions()
    canva_log = load_canva_log()
    keep_rels = [rel for rel, v in decisions.items() if v.get("decision") == "keep"]
    if not keep_rels:
        return jsonify({"summary": "No images marked Keep.", "log": [], "uploaded": 0, "total": 0})

    log: list[str] = []
    uploaded = 0
    skipped = 0
    failed = 0

    headers = {"Authorization": f"Bearer {CANVA_API_TOKEN}"}

    for rel in keep_rels:
        if rel in canva_log and canva_log[rel].get("asset_id"):
            log.append(f"⏭  {rel}: already uploaded (asset {canva_log[rel]['asset_id']})")
            skipped += 1
            continue

        # Public URL — Canva must be able to reach this
        url = f"{PUBLIC_BASE_URL.rstrip('/')}/img/{urllib.parse.quote(rel)}"
        # Filename in Canva = local filename
        fname = pathlib.Path(rel).name

        try:
            # Step 1: create asset upload job from URL
            r = requests.post(
                "https://api.canva.com/rest/v1/url-asset-uploads",
                headers={**headers, "Content-Type": "application/json"},
                json={"url": url, "name": fname},
                timeout=60,
            )
            if r.status_code not in (200, 201, 202):
                log.append(f"✗  {rel}: HTTP {r.status_code} {r.text[:200]}")
                failed += 1
                continue

            job = r.json().get("job", {})
            job_id = job.get("id")
            if not job_id:
                log.append(f"✗  {rel}: no job id in response")
                failed += 1
                continue

            # Step 2: poll for completion (up to ~60s)
            asset_id = None
            for _ in range(30):
                pr = requests.get(
                    f"https://api.canva.com/rest/v1/url-asset-uploads/{job_id}",
                    headers=headers,
                    timeout=30,
                )
                if pr.status_code == 200:
                    pjob = pr.json().get("job", {})
                    status = pjob.get("status")
                    if status == "success":
                        asset_id = pjob.get("asset", {}).get("id")
                        break
                    if status == "failed":
                        log.append(f"✗  {rel}: job failed — {pjob.get('error', {}).get('message', 'unknown')}")
                        break
                time.sleep(2)

            if not asset_id:
                log.append(f"✗  {rel}: upload did not complete in time")
                failed += 1
                continue

            # Step 3: optionally move to folder
            if CANVA_FOLDER_ID:
                mr = requests.post(
                    f"https://api.canva.com/rest/v1/folders/{CANVA_FOLDER_ID}/items",
                    headers={**headers, "Content-Type": "application/json"},
                    json={"item": {"type": "asset", "id": asset_id}},
                    timeout=30,
                )
                folder_status = "ok" if mr.status_code in (200, 201, 204) else f"move-failed {mr.status_code}"
            else:
                folder_status = "no-folder"

            canva_log[rel] = {"asset_id": asset_id, "ts": time.time(), "folder": folder_status}
            save_canva_log(canva_log)
            log.append(f"✓  {rel} → asset {asset_id} ({folder_status})")
            uploaded += 1

        except Exception as e:
            log.append(f"✗  {rel}: {e}")
            failed += 1

    summary = f"Uploaded {uploaded}, skipped {skipped} (already done), failed {failed}, total kept {len(keep_rels)}"
    return jsonify({
        "summary": summary,
        "log": log,
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "total": len(keep_rels),
    })


# ─── Canva OAuth re-authorization (added 2026-05-04) ──────────────────────
# Why: refresh_token lineage gets revoked occasionally (90-day inactivity, app
# revoke in Canva account settings, etc.) — when that happens _refresh_canva_token
# returns None forever and "Upload to Canva" silently fails with auth error.
# These routes let the user click "↻ Reconnect Canva" to redo the OAuth dance.
#
# IMPORTANT: the redirect_uri must be registered EXACTLY in the Canva
# Developer Portal under Authentication → Redirect URLs:
#     https://static.253.118.104.178.clients.your-server.de/review/canva/callback
def _canva_redirect_uri() -> str:
    return f"{PUBLIC_BASE_URL.rstrip('/')}/canva/callback"


@app.route("/canva/start")
def canva_oauth_start():
    if not CANVA_CLIENT_ID:
        return "CANVA_CLIENT_ID not configured in .env", 500
    state = secrets.token_urlsafe(24)
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    CANVA_OAUTH_STATE_FILE.write_text(json.dumps({
        "state": state, "code_verifier": code_verifier, "ts": time.time()
    }))
    params = {
        "response_type": "code",
        "client_id": CANVA_CLIENT_ID,
        "redirect_uri": _canva_redirect_uri(),
        "scope": CANVA_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return redirect(f"{CANVA_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}")


@app.route("/canva/callback")
def canva_oauth_callback():
    code = request.args.get("code")
    state = request.args.get("state")
    error = request.args.get("error")
    if error:
        return (f"<h2>Canva auth error: {escape(error)}</h2>"
                f"<p>{escape(request.args.get('error_description',''))}</p>"), 400
    if not code or not state:
        return "Missing code or state", 400
    if not CANVA_OAUTH_STATE_FILE.exists():
        return "No pending OAuth state — start over via /canva/start", 400
    try:
        saved = json.loads(CANVA_OAUTH_STATE_FILE.read_text())
    except Exception:
        return "Corrupt OAuth state file — start over", 400
    if state != saved.get("state"):
        return "State mismatch — possible CSRF, start over", 400
    body = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": CANVA_CLIENT_ID,
        "redirect_uri": _canva_redirect_uri(),
        "code_verifier": saved.get("code_verifier", ""),
    }
    if CANVA_CLIENT_SECRET:
        body["client_secret"] = CANVA_CLIENT_SECRET
    r = requests.post(
        CANVA_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if r.status_code != 200:
        return (f"<h2>Canva token exchange failed: {r.status_code}</h2>"
                f"<pre>{escape(r.text[:500])}</pre>"), 400
    j = r.json()
    if "access_token" not in j:
        return f"<h2>No access_token in response</h2><pre>{escape(json.dumps(j))}</pre>", 400
    CANVA_TOKEN_FILE.write_text(json.dumps({
        "access_token": j["access_token"],
        "expires_at": time.time() + int(j.get("expires_in", 14400)) - 60,
        "refresh_token": j.get("refresh_token", ""),
    }))
    # Persist new refresh_token to .env so service restart keeps working
    new_rt = j.get("refresh_token")
    if new_rt and ENV_FILE.exists():
        try:
            lines = ENV_FILE.read_text().splitlines()
            replaced = False
            new_lines = []
            for line in lines:
                if line.startswith("CANVA_REFRESH_TOKEN="):
                    new_lines.append(f"CANVA_REFRESH_TOKEN={new_rt}")
                    replaced = True
                else:
                    new_lines.append(line)
            if not replaced:
                new_lines.append(f"CANVA_REFRESH_TOKEN={new_rt}")
            ENV_FILE.write_text("\n".join(new_lines) + "\n")
            global CANVA_REFRESH_TOKEN
            CANVA_REFRESH_TOKEN = new_rt
        except Exception:
            pass
    try:
        CANVA_OAUTH_STATE_FILE.unlink()
    except Exception:
        pass
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Canva connected</title>'
        '<style>body{font-family:-apple-system,sans-serif;max-width:520px;margin:80px auto;padding:24px;text-align:center;}'
        'h2{color:#3a7d5f;}button{margin-top:18px;padding:10px 24px;font-size:14px;border-radius:6px;'
        'border:1px solid #e3dfd6;background:#fff;cursor:pointer;}</style></head><body>'
        '<h2>Canva connected ✓</h2>'
        '<p>You can close this window. Upload to Canva should work again.</p>'
        '<button onclick="window.close()">Close</button>'
        '</body></html>'
    )


@app.route("/canva/status")
def canva_oauth_status():
    """Returns whether a valid (or refreshable) Canva token exists.
    UI uses this to show/hide the "Reconnect Canva" button.
    """
    # Check cached token file first
    if CANVA_TOKEN_FILE.exists():
        try:
            d = json.loads(CANVA_TOKEN_FILE.read_text())
            if d.get("access_token") and d.get("expires_at", 0) > time.time() + 60:
                return jsonify({"ok": True, "expires_at": d.get("expires_at"), "now": time.time()})
        except Exception:
            pass
    # Try to refresh — if it works, we're good
    if CANVA_REFRESH_TOKEN and CANVA_CLIENT_ID:
        if _refresh_canva_token():
            return jsonify({"ok": True, "refreshed": True})
    return jsonify({"ok": False, "needs_auth": True})


@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8196)))
