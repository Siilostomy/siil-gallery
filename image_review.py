#!/usr/bin/env python3
"""SIIL Gallery — keep/delete decisions on a folder of generated images.

Each batch lives under a folder in DATA_DIR. The app shows a feed of cards,
one per image, with Keep / Delete / Regen buttons and a per-card comment box.

Run:
    pip install flask requests pillow
    DATA_DIR=/home/siil_ostomy/image-review/data python image_review.py
    # binds to 127.0.0.1:8196 by default

Canva env (set in /home/siil_ostomy/image-review/.env):
    CANVA_API_TOKEN     — OAuth access token from Canva Developer portal
    CANVA_FOLDER_ID     — (optional) default folder to drop assets in
    PUBLIC_BASE_URL     — public URL prefix for image serving (used in upload-from-url)
    GEMINI_API_KEY      — Gemini API key for server-side regen
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
import threading
import time
import urllib.parse
import uuid
from html import escape
from io import BytesIO

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
CANVA_CLIENT_SECRET = os.environ.get("CANVA_CLIENT_SECRET", "")
CANVA_TOKEN_FILE = DATA_DIR.parent / "canva_token.json"
CANVA_FOLDER_ID = os.environ.get("CANVA_FOLDER_ID", "")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://static.253.118.104.178.clients.your-server.de/review")

# ── Regen / Gemini ────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL_REFS_DIR = DATA_DIR.parent / "model_refs"
COMMENTS_FILE = DATA_DIR.parent / "comments.json"
REGEN_DIR = DATA_DIR.parent / "regen_temp"
REGEN_DIR.mkdir(parents=True, exist_ok=True)
REGEN_JOBS: dict = {}
REGEN_LOCK = threading.Lock()
PKCE_STATE: dict = {}  # state -> code_verifier

# Model portrait filename map (add as files are uploaded to model_refs/)
MODEL_PORTRAITS: dict[str, str] = {
    "Amara":   "Amara_portrait.jpg",
    "Kim":     "Kim_portrait.jpg",
    "Bruce":   "Bruce_portrait.jpg",
    "Duli":    "Duli_portrait.jpg",
    "Reed":    "Reed_portrait.jpg",
    "Sara":    "Sara_portrait.jpg",
    "Mollie":  "Mollie_portrait.jpg",
    "Tara":    "Tara_portrait.jpg",
    "Colleen": "Colleen_portrait.jpg",
}
WRAP_REF = "Gracia_basic_black.jpg"  # shape reference for all wrap colours


# ─────────────────────────────────────────────────────────────────────────────
# Canva token helpers
# ─────────────────────────────────────────────────────────────────────────────

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
    global CANVA_API_TOKEN
    refresh = CANVA_REFRESH_TOKEN
    # Also check canva_token.json for a newer refresh token
    if CANVA_TOKEN_FILE.exists():
        try:
            d = json.loads(CANVA_TOKEN_FILE.read_text())
            if d.get("refresh_token"):
                refresh = d["refresh_token"]
        except Exception:
            pass
    if not refresh or not CANVA_CLIENT_ID:
        return None
    body = {
        "grant_type": "refresh_token",
        "refresh_token": refresh,
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
            "refresh_token": j.get("refresh_token", refresh),
        }))
        CANVA_API_TOKEN = access
        return access
    except Exception:
        return None


def _canva_headers() -> dict:
    tok = _load_canva_token()
    return {"Authorization": f"Bearer {tok}"}


# ─────────────────────────────────────────────────────────────────────────────
# Comments helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_comments() -> dict:
    if COMMENTS_FILE.exists():
        try:
            return json.loads(COMMENTS_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_comments(d: dict) -> None:
    COMMENTS_FILE.write_text(json.dumps(d, indent=2))


# ─────────────────────────────────────────────────────────────────────────────
# Regen helpers
# ─────────────────────────────────────────────────────────────────────────────

def _b64_file(path: pathlib.Path) -> str | None:
    if path.exists():
        return base64.b64encode(path.read_bytes()).decode()
    return None


def _build_regen_parts(meta: dict, comment: str) -> list:
    model   = meta.get("model", "")
    color   = meta.get("color", "")
    typ     = meta.get("type", "")
    scene   = meta.get("scene", "")
    product = meta.get("product", "SIIL Ostomy Wrap")

    portrait_file = MODEL_PORTRAITS.get(model)
    portrait_b64  = _b64_file(MODEL_REFS_DIR / portrait_file) if portrait_file else None
    wrap_b64      = _b64_file(MODEL_REFS_DIR / WRAP_REF)

    prompt = (
        f"Regenerate this premium fashion editorial photograph.\n\n"
        f"ORIGINAL CONTEXT: {product} — model {model} — {color} colour — {typ} shot — scene: {scene}\n\n"
        f"ADJUSTMENT INSTRUCTION (apply this and only this change):\n{comment}\n\n"
        f"Keep everything else identical: model identity, face, skin, hair, "
        f"product colour and shape, scene type, composition, lighting quality.\n"
    )

    parts: list = [{"text": prompt}]
    if portrait_b64:
        parts.append({"text": f"Ref 1 — {model} identity (keep face, skin, hair exactly):"})
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": portrait_b64}})
    if wrap_b64:
        parts.append({"text": "Ref 2 — SIIL product shape reference (keep wrap silhouette exactly):"})
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": wrap_b64}})
    return parts


def _save_webp_regen(raw_bytes: bytes, out_path: pathlib.Path, max_kb: int = 320) -> int:
    from PIL import Image
    img = Image.open(BytesIO(raw_bytes)).convert("RGB")
    w, h = img.size
    new_h = w // 2
    if new_h < h:
        top = (h - new_h) // 2
        img = img.crop((0, top, w, top + new_h))
    img = img.resize((2880, 1440), Image.LANCZOS)
    for q in [85, 80, 75, 70, 65]:
        buf = BytesIO()
        img.save(buf, "WEBP", quality=q, method=6)
        if buf.tell() <= max_kb * 1024:
            out_path.write_bytes(buf.getvalue())
            return buf.tell() // 1024
    buf = BytesIO()
    img.save(buf, "WEBP", quality=65, method=6)
    out_path.write_bytes(buf.getvalue())
    return buf.tell() // 1024


def run_regen(rel: str, comment: str, job_id: str) -> None:
    """Background thread: generate new image via Gemini, store result."""
    try:
        meta  = parse_filename_meta(pathlib.Path(rel).name)
        parts = _build_regen_parts(meta, comment)
        body  = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": "16:9"},
            },
        }
        url = (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"models/gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
        )
        for attempt in range(5):
            try:
                r = requests.post(url, json=body, timeout=180)
                if r.status_code != 200:
                    time.sleep(3)
                    continue
                data = r.json()
                for c in data.get("candidates", []):
                    for p in c.get("content", {}).get("parts", []):
                        if "inlineData" in p:
                            raw = base64.b64decode(p["inlineData"]["data"])
                            out_path = REGEN_DIR / f"{job_id}.webp"
                            _save_webp_regen(raw, out_path)
                            with REGEN_LOCK:
                                REGEN_JOBS[job_id] = {
                                    "status": "done",
                                    "path": str(out_path),
                                    "rel": rel,
                                }
                            return
                # Check for safety block
                for c in data.get("candidates", []):
                    if c.get("finishReason") in ("SAFETY", "OTHER"):
                        with REGEN_LOCK:
                            REGEN_JOBS[job_id] = {
                                "status": "error",
                                "error": f"Safety block on attempt {attempt+1}. Try rewording the instruction.",
                                "rel": rel,
                            }
                        return
                time.sleep(3)
            except Exception as e:
                time.sleep(2)
        with REGEN_LOCK:
            REGEN_JOBS[job_id] = {
                "status": "error",
                "error": "Generation failed after 5 attempts",
                "rel": rel,
            }
    except Exception as e:
        with REGEN_LOCK:
            REGEN_JOBS[job_id] = {
                "status": "error",
                "error": str(e)[:300],
                "rel": rel,
            }


# ─────────────────────────────────────────────────────────────────────────────
# Flask app
# ─────────────────────────────────────────────────────────────────────────────

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
    for batch_dir in sorted(DATA_DIR.iterdir()):
        if not batch_dir.is_dir():
            continue
        images = []
        for f in sorted(batch_dir.iterdir()):
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
    batches  = list_batches()
    facets   = collect_facets(batches)
    comments = load_comments()
    total    = sum(len(b["images"]) for b in batches)
    decisions = load_decisions()
    n_keep     = sum(1 for v in decisions.values() if v.get("decision") in ("keep", "uploaded"))
    n_delete   = sum(1 for v in decisions.values() if v.get("decision") == "delete")
    n_undecided = total - n_keep - n_delete

    cards_html = []
    for b in batches:
        cards_html.append(
            f'<h2 class="batch-h">{escape(b["name"])} '
            f'<span class="batch-count">{len(b["images"])} images</span></h2>'
        )
        cards_html.append('<div class="batch-grid">')
        for img in b["images"]:
            d           = img["decision"]
            cls         = f' decided-{d}' if d else ""
            del_active  = "active" if d == "delete" else ""
            uploaded_cls = " uploaded" if d == "uploaded" else ""
            canva_active = "active" if d == "uploaded" else ""
            asset_id    = decisions.get(img['rel_path'], {}).get('asset_id', '')
            canva_btn_label    = "✓ In Canva" if d == "uploaded" else "↑ Canva"
            canva_btn_disabled = "disabled" if d == "uploaded" else ""
            asset_badge = (
                f'<div class="asset-badge" title="Canva asset {escape(asset_id)}">'
                f'→ Canva · {escape(asset_id[:10])}…</div>'
            ) if d == "uploaded" and asset_id else ""
            saved_comment = escape(comments.get(img['rel_path'], ''))
            data_attrs = (
                f'data-product="{escape(img.get("product",""))}" '
                f'data-model="{escape(img.get("model",""))}" '
                f'data-color="{escape(img.get("color",""))}" '
                f'data-aspect="{escape(img.get("aspect",""))}" '
                f'data-type="{escape(img.get("type",""))}" '
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
                <div class="comment-row">
                  <textarea class="card-comment" placeholder="Add instruction for re-gen…" onblur="saveComment('{escape(img['rel_path'])}', this)">{saved_comment}</textarea>
                  <button class="btn-regen" onclick="regenOne('{escape(img['rel_path'])}', this)" title="Re-generate with AI">↺ Regen</button>
                </div>
                {asset_badge}
                <div class="card-status"></div>
              </div>
            </article>''')
        cards_html.append('</div>')

    body = "\n".join(cards_html) if batches else '<p class="empty">No images yet. Upload to data/&lt;batch&gt;/</p>'

    def _opts(values):
        return "\n".join(f'<option value="{escape(v)}">{escape(v)}</option>' for v in values)

    canva_ok = bool(_load_canva_token())
    canva_auth_badge = "" if canva_ok else '<span style="color:#b5755a;font-size:12px;margin-left:6px" title="Canva token invalid — click Re-auth">⚠ Canva</span>'

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
  .topbar .actions {{ display:flex; gap:8px; align-items:center; }}
  .topbar button {{ font-size:13px; padding:7px 16px; border-radius:6px; border:1px solid var(--rule); background:#fff; cursor:pointer; }}
  .topbar button.danger {{ background:var(--bad); color:#fff; border-color:var(--bad); }}
  .topbar button.canva {{ background:#7d2ae8; color:#fff; border-color:#7d2ae8; }}
  .topbar button.reauth {{ background:#e87d2a; color:#fff; border-color:#e87d2a; font-size:12px; padding:6px 12px; }}
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
  /* Comment + Regen row */
  .comment-row {{ display:flex; gap:6px; margin-top:8px; align-items:flex-start; }}
  .card-comment {{ flex:1; font-size:12px; padding:6px 8px; border:1px solid var(--rule); border-radius:6px;
                   resize:vertical; min-height:38px; max-height:100px; font-family:inherit; color:var(--text); line-height:1.4; }}
  .card-comment:focus {{ outline:none; border-color:var(--primary); box-shadow:0 0 0 2px rgba(61,92,122,.15); }}
  .card-comment::placeholder {{ color:var(--muted); font-style:italic; }}
  .btn-regen {{ padding:6px 10px; font-size:13px; font-weight:700; border-radius:6px; border:1px solid var(--rule);
                background:#fff; cursor:pointer; white-space:nowrap; flex-shrink:0; }}
  .btn-regen:hover {{ background:#e8f4ff; border-color:var(--primary); color:var(--primary); }}
  .btn-regen:disabled {{ opacity:.5; cursor:default; }}
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
  .filters {{ position:sticky; top:60px; z-index:40; background:#fff; border-bottom:1px solid var(--rule); padding:10px 24px; display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
  .filters input, .filters select {{ font-size:13px; padding:7px 12px; border:1px solid var(--rule); border-radius:6px; background:#fff; min-width:140px; }}
  .filters input {{ flex:1; min-width:200px; max-width:340px; }}
  .filters button {{ font-size:13px; padding:7px 14px; border:1px solid var(--rule); border-radius:6px; background:#fff; cursor:pointer; }}
  .filters button:hover {{ background:#f4f3ee; }}
  .filter-count {{ font-size:12px; color:var(--muted); margin-left:auto; }}
  /* Regen comparison modal */
  .regen-modal-inner {{ max-width:1000px !important; width:95% !important; }}
  .regen-compare {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin:16px 0; }}
  .regen-side {{ display:flex; flex-direction:column; align-items:center; gap:8px; }}
  .regen-side img {{ width:100%; max-height:420px; object-fit:contain; border-radius:6px; border:1px solid var(--rule); }}
  .regen-label {{ font-size:12px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }}
  .regen-actions {{ display:flex; gap:10px; justify-content:center; margin-top:16px; flex-wrap:wrap; }}
  .regen-actions button {{ padding:11px 22px; font-size:14px; font-weight:600; border-radius:7px; border:0; cursor:pointer; }}
  .btn-regen-accept {{ background:var(--good); color:#fff; }}
  .btn-regen-accept:hover {{ background:#2f6550; }}
  .btn-regen-both {{ background:var(--primary); color:#fff; }}
  .btn-regen-both:hover {{ background:#2f4a64; }}
  .btn-regen-discard {{ background:#fff; color:var(--muted); border:1px solid var(--rule) !important; }}
  .btn-regen-discard:hover {{ background:#f4f3ee; }}
  .regen-spinner {{ display:inline-block; width:14px; height:14px; border:2px solid rgba(0,0,0,.15); border-top-color:var(--primary); border-radius:50%; animation:spin .7s linear infinite; vertical-align:middle; margin-right:4px; }}
  @keyframes spin {{ to {{ transform:rotate(360deg); }} }}
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
    <button class="canva" onclick="bulkUpload()">↑ Bulk upload visible</button>
    <button class="reauth" onclick="window.location.href='canva_reauth'" title="Re-authorise Canva access">🔑 Re-auth Canva</button>
    <button class="danger" onclick="applyDeletes()">Apply deletes</button>
    {canva_auth_badge}
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
<!-- Regen comparison modal -->
<div id="regen-modal" class="modal-bg" onclick="if(event.target===this)regenAction('discard')">
  <div class="modal regen-modal-inner">
    <h3 id="regen-modal-title">🎨 Generation Complete</h3>
    <p id="regen-modal-status" style="font-size:13px;color:var(--muted);margin:4px 0 0">Compare original vs new — choose an action:</p>
    <div class="regen-compare">
      <div class="regen-side">
        <div class="regen-label">Original</div>
        <img id="regen-orig" src="">
      </div>
      <div class="regen-side">
        <div class="regen-label">New</div>
        <img id="regen-new" src="" onerror="this.alt='Loading…'">
      </div>
    </div>
    <div class="regen-actions">
      <button class="btn-regen-accept" onclick="regenAction('replace')">✓ Accept — replace original</button>
      <button class="btn-regen-both"   onclick="regenAction('keep_both')">＋ Keep both</button>
      <button class="btn-regen-discard" onclick="regenAction('discard')">✗ Discard</button>
    </div>
  </div>
</div>
{filters_html}
<main>
{body}
</main>
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
// ── Decide / Delete ──────────────────────────────────────────────────────────
function decide(rel, action, btn) {{
  const card = btn.closest('.card');
  if (action === 'delete') {{
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

// ── Filters ──────────────────────────────────────────────────────────────────
function applyFilters() {{
  const q  = (document.getElementById('f-search').value || '').toLowerCase();
  const fp = document.getElementById('f-product').value;
  const fm = document.getElementById('f-model').value;
  const fa = document.getElementById('f-aspect').value;
  const ft = document.getElementById('f-type').value;
  const fc = document.getElementById('f-color').value;
  const fd = document.getElementById('f-decision').value;
  let shown = 0, total = 0;
  document.querySelectorAll('.card').forEach(c => {{
    total++;
    const okSearch = !q || (c.dataset.search || '').includes(q);
    const okProd   = !fp || c.dataset.product === fp;
    const okModel  = !fm || c.dataset.model === fm;
    const okAsp    = !fa || c.dataset.aspect === fa;
    const okType   = !ft || c.dataset.type === ft;
    const okColor  = !fc || c.dataset.color === fc;
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
  document.getElementById('filter-count').textContent = `Showing ${{shown}} / ${{total}}`;
}}

function clearFilters() {{
  ['f-search','f-product','f-model','f-aspect','f-type','f-color','f-decision'].forEach(id => {{
    const el = document.getElementById(id);
    if (el) el.value = '';
  }});
  applyFilters();
}}

// ── Canva upload ─────────────────────────────────────────────────────────────
function uploadOne(rel, btn) {{
  const card   = btn.closest('.card');
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

// ── Comment save ─────────────────────────────────────────────────────────────
function saveComment(rel, ta) {{
  const txt = ta.value;
  fetch('comment', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rel: rel, comment: txt}})
  }});
}}

// ── Regen ─────────────────────────────────────────────────────────────────────
let regenJobId = null;
let regenRel   = null;
let regenCard  = null;

function regenOne(rel, btn) {{
  const card    = btn.closest('.card');
  const ta      = card.querySelector('.card-comment');
  const comment = ta ? ta.value.trim() : '';
  if (!comment) {{
    ta && ta.focus();
    ta && (ta.style.borderColor = 'var(--bad)');
    setTimeout(() => {{ if (ta) ta.style.borderColor = ''; }}, 2000);
    return;
  }}
  btn.disabled = true;
  btn.innerHTML = '<span class="regen-spinner"></span>';
  const status = card.querySelector('.card-status');
  status.className = 'card-status uploading';
  status.textContent = 'Sending to Gemini…';

  fetch('regen', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{rel, comment}})
  }}).then(r => r.json()).then(d => {{
    if (!d.ok) {{
      btn.disabled = false; btn.textContent = '↺ Regen';
      status.className = 'card-status err';
      status.textContent = '✗ ' + (d.error || 'Failed to start');
      return;
    }}
    const jobId = d.job_id;
    status.textContent = 'Generating… (this takes ~20-60s)';
    const poll = setInterval(() => {{
      fetch('regen_poll/' + jobId).then(r => r.json()).then(p => {{
        if (p.status === 'done') {{
          clearInterval(poll);
          btn.disabled = false; btn.textContent = '↺ Regen';
          status.className = 'card-status ok';
          status.textContent = '✓ Done! See popup ↑';
          const origImg = card.querySelector('.image-wrap img');
          showRegenModal(rel, jobId, card, origImg ? origImg.src : '');
        }} else if (p.status === 'error') {{
          clearInterval(poll);
          btn.disabled = false; btn.textContent = '↺ Regen';
          status.className = 'card-status err';
          status.textContent = '✗ ' + (p.error || 'Generation failed');
        }}
      }}).catch(() => {{}});
    }}, 4000);
  }}).catch(e => {{
    btn.disabled = false; btn.textContent = '↺ Regen';
    status.className = 'card-status err';
    status.textContent = '✗ ' + e;
  }});
}}

function showRegenModal(rel, jobId, card, origSrc) {{
  regenJobId = jobId;
  regenRel   = rel;
  regenCard  = card;
  document.getElementById('regen-orig').src = origSrc;
  document.getElementById('regen-new').src  = 'regen_img/' + jobId + '?t=' + Date.now();
  document.getElementById('regen-modal-title').textContent = '🎨 Generation Complete';
  document.getElementById('regen-modal-status').textContent = 'Compare original (left) vs new (right). Choose an action:';
  document.getElementById('regen-modal').classList.add('show');
}}

function regenAction(action) {{
  if (!regenJobId) return;
  fetch('regen_accept', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{job_id: regenJobId, rel: regenRel, action}})
  }}).then(r => r.json()).then(d => {{
    document.getElementById('regen-modal').classList.remove('show');
    if (action === 'replace' && regenCard) {{
      // Bust the image cache on the card
      const img = regenCard.querySelector('.image-wrap img');
      if (img) img.src = img.src.split('?')[0] + '?t=' + Date.now();
      const status = regenCard.querySelector('.card-status');
      if (status) {{ status.className = 'card-status ok'; status.textContent = '✓ Replaced'; }}
    }} else if (action === 'keep_both') {{
      window.location.reload();  // show the new card
    }}
    regenJobId = null; regenRel = null; regenCard = null;
  }}).catch(e => {{
    alert('Error: ' + e);
  }});
}}

// ── Action history for undo ──────────────────────────────────────────────────
const actionHistory = [];

function pushAction(action) {{
  actionHistory.push(action);
  if (actionHistory.length > 50) actionHistory.shift();
}}

function undoLast() {{
  if (actionHistory.length === 0) return;
  const action = actionHistory.pop();
  const card = document.querySelector(`.card[data-rel="${{action.rel ? action.rel.replace(/"/g, '\\\\"') : ''}}"]`);
  if (!card) {{
    if (action.kind === 'apply_deletes' || action.kind === 'delete_now') {{
      undoApplyDeletes();
    }}
    return;
  }}
  if (action.kind === 'apply_deletes' || action.kind === 'delete_now') {{
    undoApplyDeletes();
    return;
  }}
  if (action.kind === 'canva') {{
    fetch('canva_undo', {{
      method: 'POST', headers: {{'Content-Type':'application/json'}},
      body: JSON.stringify({{rel: action.rel, asset_id: action.prevAssetId || ''}})
    }}).then(r => r.json()).then(d => {{
      card.classList.remove('uploaded');
      const cardBtn = card.querySelector('.btn-canva');
      if (cardBtn) {{ cardBtn.classList.remove('active'); cardBtn.textContent = '↑ Canva'; cardBtn.disabled = false; }}
      const status = card.querySelector('.card-status');
      if (status) {{ status.className = 'card-status'; status.textContent = ''; }}
      if (lbCurrentCard === card) openLightbox(card);
    }});
  }} else if (action.kind === 'delete' || action.kind === 'keep') {{
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

// ── Lightbox ─────────────────────────────────────────────────────────────────
let lbCurrentCard = null;

function getVisibleCards() {{
  return Array.from(document.querySelectorAll('.card')).filter(c => c.style.display !== 'none');
}}

function openLightbox(card) {{
  if (!card) return;
  lbCurrentCard = card;
  const img      = card.querySelector('.image-wrap img');
  const filename = card.querySelector('.filename')?.textContent || '';
  document.getElementById('lb-img').src = img.src;
  document.getElementById('lb-name').textContent = filename;
  const visible = getVisibleCards();
  const idx = visible.indexOf(card);
  document.getElementById('lb-counter').textContent = `${{idx + 1}} / ${{visible.length}}`;
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
    next.scrollIntoView({{behavior: 'smooth', block: 'center'}});
  }}
}}

function lightboxAction(kind) {{
  if (!lbCurrentCard) return;
  const rel  = lbCurrentCard.dataset.rel;
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
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {{
    e.preventDefault(); undoLast(); return;
  }}
  const lb = document.getElementById('lightbox');
  if (!lb.classList.contains('show')) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'Escape')                                   {{ e.preventDefault(); closeLightbox(); }}
  else if (e.key === 'ArrowRight')                          {{ e.preventDefault(); navLightbox(1); }}
  else if (e.key === 'ArrowLeft')                           {{ e.preventDefault(); navLightbox(-1); }}
  else if (e.key === 'Enter')                               {{ e.preventDefault(); lightboxAction('canva'); }}
  else if (e.key === 'Delete' || e.key === 'Backspace')     {{ e.preventDefault(); lightboxAction('delete'); }}
}});

document.getElementById('lightbox').addEventListener('click', (e) => {{
  if (e.target.id === 'lightbox') closeLightbox();
}});
</script>
</body></html>"""
    resp = app.make_response(html)
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Image serving
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/img/<path:rel>")
def serve_img(rel: str):
    rel = rel.replace("..", "")
    p = (DATA_DIR / rel).resolve()
    if not str(p).startswith(str(DATA_DIR)) or not p.exists():
        abort(404)
    return send_file(p)


# ─────────────────────────────────────────────────────────────────────────────
# Decision routes
# ─────────────────────────────────────────────────────────────────────────────

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
    data = request.get_json() or {}
    rel = data.get("rel", "").replace("..", "")
    src = (DATA_DIR / rel).resolve()
    if not str(src).startswith(str(DATA_DIR)) or not src.exists():
        return jsonify({"ok": False, "error": "file not found"}), 404
    batch_id = time.strftime("%Y%m%d-%H%M%S-%f")
    dst = TRASH_DIR / f"{batch_id}_{rel.replace('/', '__')}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    decisions = load_decisions()
    decisions.pop(rel, None)
    save_decisions(decisions)
    log = _load_apply_log()
    log.append({"batch_id": batch_id, "ts": time.time(), "moves": [{"rel": rel, "trash_path": str(dst)}]})
    log = log[-50:]
    _save_apply_log(log)
    return jsonify({"ok": True, "batch_id": batch_id, "rel": rel})


@app.route("/apply_deletes", methods=["POST"])
def apply_deletes():
    decisions = load_decisions()
    batch_id = time.strftime("%Y%m%d-%H%M%S")
    moves = []
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
    if moves:
        log = _load_apply_log()
        log.append({"batch_id": batch_id, "ts": time.time(), "moves": moves})
        log = log[-20:]
        _save_apply_log(log)
    return jsonify({"moved": len(moves), "batch_id": batch_id})


@app.route("/undo_apply_deletes", methods=["POST"])
def undo_apply_deletes():
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


# ─────────────────────────────────────────────────────────────────────────────
# Comment routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/comment", methods=["GET", "POST"])
def comment():
    if request.method == "GET":
        rel = request.args.get("rel", "").replace("..", "")
        comments = load_comments()
        return jsonify({"comment": comments.get(rel, "")})
    data = request.get_json() or {}
    rel  = data.get("rel", "").replace("..", "")
    text = data.get("comment", "")
    comments = load_comments()
    if text.strip():
        comments[rel] = text
    else:
        comments.pop(rel, None)
    save_comments(comments)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# Regen routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/regen", methods=["POST"])
def regen():
    if not GEMINI_API_KEY:
        return jsonify({"ok": False, "error": "GEMINI_API_KEY not configured on server"}), 400
    data    = request.get_json() or {}
    rel     = data.get("rel", "").replace("..", "")
    comment = data.get("comment", "").strip()
    if not comment:
        return jsonify({"ok": False, "error": "No instruction provided in comment"}), 400
    job_id = str(uuid.uuid4())
    with REGEN_LOCK:
        REGEN_JOBS[job_id] = {"status": "pending", "rel": rel}
    t = threading.Thread(target=run_regen, args=(rel, comment, job_id), daemon=True)
    t.start()
    return jsonify({"ok": True, "job_id": job_id})


@app.route("/regen_poll/<job_id>")
def regen_poll(job_id: str):
    job_id = re.sub(r"[^a-f0-9\-]", "", job_id)
    with REGEN_LOCK:
        job = REGEN_JOBS.get(job_id)
    if not job:
        return jsonify({"status": "not_found"}), 404
    result = {"status": job["status"], "rel": job.get("rel", "")}
    if job["status"] == "done":
        result["regen_url"] = f"/regen_img/{job_id}"
    elif job["status"] == "error":
        result["error"] = job.get("error", "unknown")
    return jsonify(result)


@app.route("/regen_img/<job_id>")
def regen_img(job_id: str):
    job_id = re.sub(r"[^a-f0-9\-]", "", job_id)
    p = REGEN_DIR / f"{job_id}.webp"
    if not p.exists():
        abort(404)
    return send_file(p)


@app.route("/regen_accept", methods=["POST"])
def regen_accept():
    data   = request.get_json() or {}
    job_id = re.sub(r"[^a-f0-9\-]", "", data.get("job_id", ""))
    rel    = data.get("rel", "").replace("..", "")
    action = data.get("action", "discard")

    src  = REGEN_DIR / f"{job_id}.webp"
    if not src.exists():
        return jsonify({"ok": False, "error": "regen file not found"}), 404

    orig = (DATA_DIR / rel).resolve()
    if not str(orig).startswith(str(DATA_DIR)):
        return jsonify({"ok": False, "error": "invalid path"}), 400

    if action == "replace":
        orig.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(orig))
        src.unlink(missing_ok=True)
        with REGEN_LOCK:
            REGEN_JOBS.pop(job_id, None)
        return jsonify({"ok": True, "action": "replaced"})
    elif action == "keep_both":
        stem     = orig.stem
        suffix   = orig.suffix
        new_name = orig.parent / f"{stem}_regen{suffix}"
        orig.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(new_name))
        src.unlink(missing_ok=True)
        new_rel  = f"{pathlib.Path(rel).parent}/{new_name.name}"
        with REGEN_LOCK:
            REGEN_JOBS.pop(job_id, None)
        return jsonify({"ok": True, "action": "kept_both", "new_rel": new_rel})
    else:  # discard
        src.unlink(missing_ok=True)
        with REGEN_LOCK:
            REGEN_JOBS.pop(job_id, None)
        return jsonify({"ok": True, "action": "discarded"})


# ─────────────────────────────────────────────────────────────────────────────
# Canva upload routes
# ─────────────────────────────────────────────────────────────────────────────

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

    url     = f"{PUBLIC_BASE_URL.rstrip('/')}/img/{urllib.parse.quote(rel)}"
    fname   = pathlib.Path(rel).name
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
            return False, "auth failed and could not refresh — click 🔑 Re-auth Canva in toolbar", "auth"
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
            move_attempts = [
                ("https://api.canva.com/rest/v1/folders/move",
                 {"to_folder_id": CANVA_FOLDER_ID, "item_id": asset_id}),
                ("https://api.canva.com/rest/v1/folders/move-folder-item",
                 {"to_folder_id": CANVA_FOLDER_ID, "item_id": asset_id}),
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
        decisions = load_decisions()
        decisions[rel] = {"decision": "uploaded", "ts": time.time(), "asset_id": asset_id}
        save_decisions(decisions)
        return True, asset_id, f"uploaded · folder:{folder_status}"
    except Exception as e:
        return False, str(e)[:160], "err"


@app.route("/canva_undo", methods=["POST"])
def canva_undo():
    data     = request.get_json() or {}
    rel      = data.get("rel", "").replace("..", "")
    asset_id = data.get("asset_id", "")

    canva_log = load_canva_log()
    if not asset_id:
        asset_id = canva_log.get(rel, {}).get("asset_id", "")

    canva_deleted = False
    if asset_id:
        try:
            r = requests.delete(
                f"https://api.canva.com/rest/v1/assets/{asset_id}",
                headers=_canva_headers(), timeout=30,
            )
            if r.status_code == 401:
                if _refresh_canva_token():
                    r = requests.delete(
                        f"https://api.canva.com/rest/v1/assets/{asset_id}",
                        headers=_canva_headers(), timeout=30,
                    )
            canva_deleted = r.status_code in (200, 204)
        except Exception:
            pass

    canva_log.pop(rel, None)
    save_canva_log(canva_log)
    decisions = load_decisions()
    decisions.pop(rel, None)
    save_decisions(decisions)
    return jsonify({"ok": True, "canva_deleted": canva_deleted, "asset_id": asset_id})


@app.route("/upload_canva_one", methods=["POST"])
def upload_canva_one():
    data = request.get_json() or {}
    rel  = data.get("rel", "").replace("..", "")
    ok, msg, _ = _upload_one_to_canva(rel)
    if ok:
        return jsonify({"ok": True, "asset_id": msg})
    return jsonify({"ok": False, "error": msg}), 400


@app.route("/upload_canva_bulk", methods=["POST"])
def upload_canva_bulk():
    data = request.get_json() or {}
    rels = [r.replace("..", "") for r in data.get("rels", [])]
    if not rels:
        return jsonify({"summary": "No images supplied.", "log": [], "uploaded": 0, "total": 0})
    log: list[str] = []
    uploaded = 0; skipped = 0; failed = 0
    uploaded_rels: list[str] = []
    for rel in rels:
        ok, msg, status = _upload_one_to_canva(rel)
        if ok:
            if status == "already":
                log.append(f"⏭  {rel}: already uploaded ({msg})")
                skipped += 1
            else:
                log.append(f"✓  {rel} → {msg}")
                uploaded += 1; uploaded_rels.append(rel)
        else:
            log.append(f"✗  {rel}: {msg}")
            failed += 1
    return jsonify({
        "summary": f"Uploaded {uploaded}, skipped {skipped} (already), failed {failed}, total {len(rels)}",
        "log": log, "uploaded": uploaded, "skipped": skipped, "failed": failed,
        "total": len(rels), "uploaded_rels": uploaded_rels,
    })


@app.route("/upload_canva", methods=["POST"])
def upload_canva():
    """Upload all 'keep'-marked images to Canva."""
    if not CANVA_API_TOKEN:
        return jsonify({"error": "CANVA_API_TOKEN not set.", "summary": "Not configured"}), 400
    decisions  = load_decisions()
    canva_log  = load_canva_log()
    keep_rels  = [rel for rel, v in decisions.items() if v.get("decision") == "keep"]
    if not keep_rels:
        return jsonify({"summary": "No images marked Keep.", "log": [], "uploaded": 0, "total": 0})
    log: list[str] = []
    uploaded = 0; skipped = 0; failed = 0
    headers = {"Authorization": f"Bearer {CANVA_API_TOKEN}"}
    for rel in keep_rels:
        if rel in canva_log and canva_log[rel].get("asset_id"):
            log.append(f"⏭  {rel}: already uploaded (asset {canva_log[rel]['asset_id']})")
            skipped += 1; continue
        url   = f"{PUBLIC_BASE_URL.rstrip('/')}/img/{urllib.parse.quote(rel)}"
        fname = pathlib.Path(rel).name
        try:
            r = requests.post("https://api.canva.com/rest/v1/url-asset-uploads",
                              headers={**headers, "Content-Type": "application/json"},
                              json={"url": url, "name": fname}, timeout=60)
            if r.status_code not in (200, 201, 202):
                log.append(f"✗  {rel}: HTTP {r.status_code} {r.text[:200]}"); failed += 1; continue
            job = r.json().get("job", {})
            job_id = job.get("id")
            if not job_id:
                log.append(f"✗  {rel}: no job id in response"); failed += 1; continue
            asset_id = None
            for _ in range(30):
                pr = requests.get(f"https://api.canva.com/rest/v1/url-asset-uploads/{job_id}",
                                  headers=headers, timeout=30)
                if pr.status_code == 200:
                    pjob = pr.json().get("job", {})
                    status = pjob.get("status")
                    if status == "success":
                        asset_id = pjob.get("asset", {}).get("id"); break
                    if status == "failed":
                        log.append(f"✗  {rel}: job failed — {pjob.get('error', {}).get('message', 'unknown')}"); break
                time.sleep(2)
            if not asset_id:
                log.append(f"✗  {rel}: upload did not complete in time"); failed += 1; continue
            if CANVA_FOLDER_ID:
                mr = requests.post(f"https://api.canva.com/rest/v1/folders/{CANVA_FOLDER_ID}/items",
                                   headers={**headers, "Content-Type": "application/json"},
                                   json={"item": {"type": "asset", "id": asset_id}}, timeout=30)
                folder_status = "ok" if mr.status_code in (200, 201, 204) else f"move-failed {mr.status_code}"
            else:
                folder_status = "no-folder"
            canva_log[rel] = {"asset_id": asset_id, "ts": time.time(), "folder": folder_status}
            save_canva_log(canva_log)
            log.append(f"✓  {rel} → asset {asset_id} ({folder_status})")
            uploaded += 1
        except Exception as e:
            log.append(f"✗  {rel}: {e}"); failed += 1
    summary = f"Uploaded {uploaded}, skipped {skipped} (already done), failed {failed}, total kept {len(keep_rels)}"
    return jsonify({"summary": summary, "log": log, "uploaded": uploaded,
                    "skipped": skipped, "failed": failed, "total": len(keep_rels)})


# ─────────────────────────────────────────────────────────────────────────────
# Canva OAuth PKCE re-auth
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/canva_reauth")
def canva_reauth():
    """Start Canva OAuth PKCE flow. Redirect to Canva auth page."""
    if not CANVA_CLIENT_ID:
        return "CANVA_CLIENT_ID not configured in .env", 400
    verifier  = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    PKCE_STATE[state] = verifier
    scopes = " ".join([
        "app:read", "asset:read", "asset:write",
        "design:content:read", "design:content:write",
        "design:meta:read", "folder:read", "folder:write",
    ])
    callback_url = f"{PUBLIC_BASE_URL.rstrip('/')}/canva_callback"
    params = urllib.parse.urlencode({
        "client_id":             CANVA_CLIENT_ID,
        "response_type":         "code",
        "redirect_uri":          callback_url,
        "scope":                 scopes,
        "code_challenge":        challenge,
        "code_challenge_method": "S256",
        "state":                 state,
    })
    return redirect(f"https://www.canva.com/api/oauth/authorize?{params}")


@app.route("/canva_callback")
def canva_callback():
    """Handle Canva OAuth redirect. Exchange code for tokens."""
    code  = request.args.get("code", "")
    state = request.args.get("state", "")
    error = request.args.get("error", "")

    if error:
        return f"<h2>Canva auth error: {escape(error)}</h2><a href='/'>← Back</a>", 400

    verifier = PKCE_STATE.pop(state, None)
    if not verifier:
        return "<h2>Invalid or expired state. Please try again.</h2><a href='/canva_reauth'>Retry</a>", 400

    callback_url = f"{PUBLIC_BASE_URL.rstrip('/')}/canva_callback"
    try:
        r = requests.post(
            "https://api.canva.com/rest/v1/oauth/token",
            data={
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  callback_url,
                "client_id":     CANVA_CLIENT_ID,
                "code_verifier": verifier,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        if r.status_code != 200:
            return f"<h2>Token exchange failed: {r.status_code}</h2><pre>{escape(r.text[:400])}</pre><a href='/canva_reauth'>Retry</a>", 400
        j       = r.json()
        access  = j.get("access_token")
        refresh = j.get("refresh_token", "")
        if not access:
            return "<h2>No access_token in Canva response</h2><a href='/canva_reauth'>Retry</a>", 400

        # Persist to canva_token.json
        CANVA_TOKEN_FILE.write_text(json.dumps({
            "access_token":  access,
            "expires_at":    time.time() + int(j.get("expires_in", 14400)) - 60,
            "refresh_token": refresh,
        }))
        # Update .env
        if ENV_FILE.exists():
            env_text = ENV_FILE.read_text()
            def _upsert_env(text: str, key: str, val: str) -> str:
                if re.search(rf"^{re.escape(key)}=", text, re.MULTILINE):
                    return re.sub(rf"^{re.escape(key)}=.*$", f"{key}={val}", text, flags=re.MULTILINE)
                return text.rstrip("\n") + f"\n{key}={val}\n"
            env_text = _upsert_env(env_text, "CANVA_API_TOKEN", access)
            if refresh:
                env_text = _upsert_env(env_text, "CANVA_REFRESH_TOKEN", refresh)
            ENV_FILE.write_text(env_text)

        return f"""<!doctype html><html><body style="font-family:-apple-system,sans-serif;text-align:center;padding:80px 20px">
<h2 style="color:#3a7d5f">✓ Canva connected!</h2>
<p style="color:#7a7367;margin:8px 0 32px">New access token saved. You can now upload images to Canva.</p>
<a href="/" style="display:inline-block;padding:14px 28px;background:#7d2ae8;color:#fff;border-radius:8px;text-decoration:none;font-weight:600">← Back to Gallery</a>
</body></html>"""
    except Exception as e:
        return f"<h2>Error: {escape(str(e))}</h2><a href='/canva_reauth'>Retry</a>", 500


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────

@app.route("/healthz")
def healthz():
    return "ok"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 8196)))
