from flask import (
    render_template, request, redirect, url_for, send_file, flash, Response,
    jsonify, send_from_directory, make_response
)
from flask_login import login_required, current_user
from sqlalchemy import or_
import io
import re
import os
import base64
import time
import requests
from urllib.parse import urlparse, parse_qs, unquote
from html import unescape

# Dotenv: carga credenciales/vars desde /opt/qventory/qventory/.env
from dotenv import load_dotenv
load_dotenv("/opt/qventory/qventory/.env")

# >>> IMPRESIÓN (lo existente)
import tempfile
import subprocess
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
# <<<

from ..extensions import db
from ..models.item import Item
from ..models.setting import Setting
from ..models.user import User
from ..helpers import (
    get_or_create_settings, generate_sku, compose_location_code,
    parse_location_code, parse_values, human_from_code, qr_label_image
)
from . import main_bp


# ---------------------- Landing pública ----------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


# ---------------------- Dashboard (protegido) ----------------------

@main_bp.route("/dashboard")
@login_required
def dashboard():
    s = get_or_create_settings(current_user)

    total_items = Item.query.filter_by(user_id=current_user.id).count()

    q = (request.args.get("q") or "").strip()
    fA = (request.args.get("A") or "").strip()
    fB = (request.args.get("B") or "").strip()
    fS = (request.args.get("S") or "").strip()
    fC = (request.args.get("C") or "").strip()
    fPlatform = (request.args.get("platform") or "").strip()

    items = Item.query.filter_by(user_id=current_user.id)

    if q:
        like = f"%{q}%"
        items = items.filter(or_(Item.title.ilike(like), Item.sku.ilike(like)))

    if s.enable_A and fA:
        items = items.filter(Item.A == fA)
    if s.enable_B and fB:
        items = items.filter(Item.B == fB)
    if s.enable_S and fS:
        items = items.filter(Item.S == fS)
    if s.enable_C and fC:
        items = items.filter(Item.C == fC)

    if fPlatform:
        col = {
            "web": Item.web_url, "ebay": Item.ebay_url, "amazon": Item.amazon_url,
            "mercari": Item.mercari_url, "vinted": Item.vinted_url,
            "poshmark": Item.poshmark_url, "depop": Item.depop_url
        }.get(fPlatform)
        if col is not None:
            items = items.filter(col.isnot(None))

    items = items.order_by(Item.created_at.desc()).all()

    def distinct(col):
        return [
            r[0] for r in db.session.query(col)
            .filter(col.isnot(None), Item.user_id == current_user.id)
            .distinct().order_by(col.asc()).all()
        ]

    options = {
        "A": distinct(Item.A) if s.enable_A else [],
        "B": distinct(Item.B) if s.enable_B else [],
        "S": distinct(Item.S) if s.enable_S else [],
        "C": distinct(Item.C) if s.enable_C else [],
    }

    PLATFORMS = [
        ("web", "Website"),
        ("ebay", "eBay"),
        ("amazon", "Amazon"),
        ("mercari", "Mercari"),
        ("vinted", "Vinted"),
        ("poshmark", "Poshmark"),
        ("depop", "Depop"),
    ]

    return render_template(
        "dashboard.html",
        items=items,
        settings=s,
        options=options,
        total_items=total_items,
        q=q, fA=fA, fB=fB, fS=fS, fC=fC,
        fPlatform=fPlatform, PLATFORMS=PLATFORMS
    )


# ---------------------- eBay config (Browse + Finding) ----------------------

EBAY_ENV = (os.environ.get("EBAY_ENV") or "production").lower()
EBAY_CLIENT_ID = os.environ.get("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.environ.get("EBAY_CLIENT_SECRET")

def _ebay_base():
    if EBAY_ENV == "sandbox":
        return {
            "oauth": "https://api.sandbox.ebay.com/identity/v1/oauth2/token",
            "browse": "https://api.sandbox.ebay.com/buy/browse/v1",
        }
    return {
        "oauth": "https://api.ebay.com/identity/v1/oauth2/token",
        "browse": "https://api.ebay.com/buy/browse/v1",
    }

_EBAY_TOKEN = {"value": None, "exp": 0}

def _get_ebay_app_token() -> str:
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        raise RuntimeError("Faltan EBAY_CLIENT_ID / EBAY_CLIENT_SECRET en .env")
    base = _ebay_base()
    now = time.time()
    if _EBAY_TOKEN["value"] and _EBAY_TOKEN["exp"] - 60 > now:
        return _EBAY_TOKEN["value"]

    basic = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    data = {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope"
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {basic}",
    }
    r = requests.post(base["oauth"], headers=headers, data=data, timeout=20)
    r.raise_for_status()
    j = r.json()
    _EBAY_TOKEN["value"] = j["access_token"]
    _EBAY_TOKEN["exp"] = now + int(j.get("expires_in", 7200))
    return _EBAY_TOKEN["value"]


# ---------------------- Helpers de parseo ----------------------

def _extract_legacy_id(url: str) -> str | None:
    m = re.search(r"/itm/(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"(\d{9,})", url)
    return m.group(1) if m else None

def _normalize_site_id(domain: str) -> str:
    d = (domain or "").lower()
    if d.endswith(".co.uk"): return "EBAY-GB"
    if d.endswith(".de"):    return "EBAY-DE"
    if d.endswith(".fr"):    return "EBAY-FR"
    if d.endswith(".it"):    return "EBAY-IT"
    if d.endswith(".es"):    return "EBAY-ES"
    if d.endswith(".com.au"):return "EBAY-AU"
    return "EBAY-US"

def _parse_seller_from_input(source: str) -> str | None:
    """
    Acepta:
      - username directo (A-Za-z0-9._-)
      - URL /usr/<seller>
      - URL /str/<store>  -> resuelve username real buscando:
          * _ssn= en query o en URL final
          * claves embebidas: sellerUsername, sellerUserName, sellerName, userId
          * texto visible "Seller: <username>" en el HTML
          * si nada aparece pero el slug es válido, usa el slug como fallback
    """
    if not source:
        return None
    s = source.strip()

    if not re.match(r"^https?://", s, re.I):
        return s if re.match(r"^[A-Za-z0-9._-]{1,64}$", s) else None

    try:
        p = urlparse(s)
        path = p.path or "/"

        m = re.search(r"/usr/([^/?#]+)", path, re.I)
        if m:
            u = unquote(m.group(1))
            return u if re.match(r"^[A-Za-z0-9._-]{1,64}$", u) else None

        q = parse_qs(p.query or "")
        if "_ssn" in q and q["_ssn"]:
            return q["_ssn"][0]

        mm = re.search(r"/str/([^/?#]+)", path, re.I)
        if mm:
            slug = unquote(mm.group(1))
            candidate = slug if re.match(r"^[A-Za-z0-9._-]{1,64}$", slug) else None

            try:
                headers = {
                    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                                   " AppleWebKit/537.36 (KHTML, like Gecko)"
                                   " Chrome/124.0.0.0 Safari/537.36"),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
                    "Cache-Control": "no-cache",
                }
                r = requests.get(s, headers=headers, timeout=20, allow_redirects=True)

                try:
                    pf = urlparse(r.url)
                    qf = parse_qs(pf.query or "")
                    if "_ssn" in qf and qf["_ssn"]:
                        return qf["_ssn"][0]
                except Exception:
                    pass

                html = r.text or ""

                m = re.search(r"[_?&]ssn=([A-Za-z0-9._%-]+)", html, re.I)
                if m:
                    return unquote(m.group(1))

                for key in [r'sellerUsername', r'sellerUserName', r'sellerName', r'userId']:
                    m = re.search(rf'"{key}"\s*:\s*"([^"]+)"', html)
                    if m and re.match(r"^[A-Za-z0-9._-]{1,64}$", m.group(1)):
                        return m.group(1)

                m = re.search(r"Seller:\s*([A-Za-z0-9._-]{1,64})", html, re.I)
                if m:
                    return m.group(1)

            except Exception:
                pass

            if candidate:
                return candidate

        return None
    except Exception:
        return None


# ---------------------- API helper: importar título desde URL (Browse) ----------------------

@main_bp.route("/api/fetch-market-title")
@login_required
def api_fetch_market_title():
    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "Missing url"}), 400
    if not re.match(r"^https?://", raw_url, re.I):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    legacy_id = _extract_legacy_id(raw_url)
    if not legacy_id:
        return jsonify({"ok": False, "error": "No se pudo extraer el legacy_item_id de la URL"}), 400

    base = _ebay_base()
    try:
        token = _get_ebay_app_token()
        r = requests.get(
            f"{base['browse']}/item/get_item_by_legacy_id",
            params={"legacy_item_id": legacy_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=20
        )
        if r.status_code == 403:
            return jsonify({"ok": False, "error": f"403 Forbidden: tu app no tiene acceso a Browse API en {EBAY_ENV}."}), 403
        if r.status_code == 404:
            return jsonify({"ok": False, "error": "404: legacy_item_id no encontrado."}), 404

        r.raise_for_status()
        data = r.json()
        title = (data.get("title") or "").strip()
        item_web_url = data.get("itemWebUrl") or raw_url

        if not title:
            return jsonify({"ok": False, "error": "La API no devolvió título"}), 502

        return jsonify({"ok": True, "marketplace": "ebay", "title": title,
                        "fill": {"title": title, "ebay_url": item_web_url}})
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response is not None else ""
        return jsonify({"ok": False, "error": f"HTTP {e.response.status_code}: {body}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- CRUD Items ----------------------

@main_bp.route("/item/new", methods=["GET", "POST"])
@login_required
def new_item():
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        listing_link = (request.form.get("listing_link") or "").strip() or None

        web_url     = (request.form.get("web_url") or "").strip() or None
        ebay_url    = (request.form.get("ebay_url") or "").strip() or None
        amazon_url  = (request.form.get("amazon_url") or "").strip() or None
        mercari_url = (request.form.get("mercari_url") or "").strip() or None
        vinted_url  = (request.form.get("vinted_url") or "").strip() or None
        poshmark_url= (request.form.get("poshmark_url") or "").strip() or None
        depop_url   = (request.form.get("depop_url") or "").strip() or None

        A  = (request.form.get("A") or "").strip() or None
        B  = (request.form.get("B") or "").strip() or None
        S_ = (request.form.get("S") or "").strip() or None
        C  = (request.form.get("C") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("main.new_item"))

        sku = generate_sku()
        loc = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        it = Item(
            user_id=current_user.id, title=title, sku=sku, listing_link=listing_link,
            web_url=web_url, ebay_url=ebay_url, amazon_url=amazon_url, mercari_url=mercari_url,
            vinted_url=vinted_url, poshmark_url=poshmark_url, depop_url=depop_url,
            A=A, B=B, S=S_, C=C, location_code=loc
        )
        db.session.add(it)
        db.session.commit()

        action = (request.form.get("submit_action") or "create").strip()
        if action == "create_another":
            flash("Item created. You can add another.", "ok")
            return render_template("new_item.html", settings=s, item=None)

        flash("Item created.", "ok")
        return redirect(url_for("main.dashboard"))

    return render_template("new_item.html", settings=s, item=None)


@main_bp.route("/item/<int:item_id>/edit", methods=["GET", "POST"])
@login_required
def edit_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        listing_link = (request.form.get("listing_link") or "").strip() or None

        web_url = (request.form.get("web_url") or "").strip() or None
        ebay_url = (request.form.get("ebay_url") or "").strip() or None
        amazon_url = (request.form.get("amazon_url") or "").strip() or None
        mercari_url = (request.form.get("mercari_url") or "").strip() or None
        vinted_url = (request.form.get("vinted_url") or "").strip() or None
        poshmark_url = (request.form.get("poshmark_url") or "").strip() or None
        depop_url = (request.form.get("depop_url") or "").strip() or None

        A = (request.form.get("A") or "").strip() or None
        B = (request.form.get("B") or "").strip() or None
        S_ = (request.form.get("S") or "").strip() or None
        C = (request.form.get("C") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("main.edit_item", item_id=item_id))

        it.title = title
        it.listing_link = listing_link
        it.web_url = web_url
        it.ebay_url = ebay_url
        it.amazon_url = amazon_url
        it.mercari_url = mercari_url
        it.vinted_url = vinted_url
        it.poshmark_url = poshmark_url
        it.depop_url = depop_url

        it.A, it.B, it.S, it.C = A, B, S_, C
        it.location_code = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        db.session.commit()
        flash("Item updated.", "ok")
        return redirect(url_for("main.dashboard"))
    return render_template("edit_item.html", item=it, settings=s)


@main_bp.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(it)
    db.session.commit()
    flash("Item deleted.", "ok")
    return redirect(url_for("main.dashboard"))


# ---------------------- Settings ----------------------

@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    s = get_or_create_settings(current_user)
    if request.method == "POST":
        s.enable_A = request.form.get("enable_A") == "on"
        s.enable_B = request.form.get("enable_B") == "on"
        s.enable_S = request.form.get("enable_S") == "on"
        s.enable_C = request.form.get("enable_C") == "on"

        s.label_A = (request.form.get("label_A") or "").strip() or "Aisle"
        s.label_B = (request.form.get("label_B") or "").strip() or "Bay"
        s.label_S = (request.form.get("label_S") or "").strip() or "Shelve"
        s.label_C = (request.form.get("label_C") or "").strip() or "Container"

        db.session.commit()
        flash("Settings saved.", "ok")
        return redirect(url_for("main.settings"))
    return render_template("settings.html", settings=s)


# ---------------------- Batch QR ----------------------

@main_bp.route("/qr/batch", methods=["GET", "POST"])
@login_required
def qr_batch():
    s = get_or_create_settings(current_user)
    if request.method == "GET":
        return render_template("batch_qr.html", settings=s)

    valsA = parse_values(request.form.get("A") or "") if s.enable_A else [""]
    valsB = parse_values(request.form.get("B") or "") if s.enable_B else [""]
    valsS = parse_values(request.form.get("S") or "") if s.enable_S else [""]
    valsC = parse_values(request.form.get("C") or "") if s.enable_C else [""]

    if s.enable_A and not valsA: valsA = [""]
    if s.enable_B and not valsB: valsB = [""]
    if s.enable_S and not valsS: valsS = [""]
    if s.enable_C and not valsC: valsC = [""]

    combos = []
    for a in valsA:
        for b in valsB:
            for s_ in valsS:
                for c in valsC:
                    code = compose_location_code(
                        A=a or None, B=b or None, S=s_ or None, C=c or None,
                        enabled=tuple(s.enabled_levels())
                    )
                    if code:
                        combos.append(code)

    if not combos:
        flash("No codes generated. Please provide at least one value.", "error")
        return redirect(url_for("main.qr_batch"))

    from ..helpers.utils import build_qr_batch_pdf
    pdf_buf = build_qr_batch_pdf(
        combos, s,
        lambda code: url_for("main.public_view_location",
                             username=current_user.username, code=code, _external=True)
    )
    return send_file(pdf_buf, mimetype="application/pdf", as_attachment=True, download_name="qr_labels.pdf")


# ---------------------- Rutas públicas por username ----------------------

@main_bp.route("/<username>/location/<code>")
def public_view_location(username, code):
    user = User.query.filter_by(username=username).first_or_404()
    s = get_or_create_settings(user)
    parts = parse_location_code(code)

    q = Item.query.filter_by(user_id=user.id)
    if s.enable_A and "A" in parts:
        q = q.filter(Item.A == parts["A"])
    if s.enable_B and "B" in parts:
        q = q.filter(Item.B == parts["B"])
    if s.enable_S and "S" in parts:
        q = q.filter(Item.S == parts["S"])
    if s.enable_C and "C" in parts:
        q = q.filter(Item.C == parts["C"])

    items = q.order_by(Item.created_at.desc()).all()
    return render_template("location.html", code=code, items=items, settings=s, parts=parts, username=username)


@main_bp.route("/<username>/qr/location/<code>.png")
def qr_for_location(username, code):
    user = User.query.filter_by(username=username).first_or_404()
    s = get_or_create_settings(user)
    parts = parse_location_code(code)
    labels = s.labels_map()
    segments = []
    if s.enable_A and parts.get("A"):
        segments.append(f"{labels['A']} {parts['A']}")
    if s.enable_B and parts.get("B"):
        segments.append(f"{labels['B']} {parts['B']}")
    if s.enable_S and parts.get("S"):
        segments.append(f"{labels['S']} {parts['S']}")
    if s.enable_C and parts.get("C"):
        segments.append(f"{labels['C']} {parts['C']}")
    human = " • ".join(segments) if segments else "Location"

    link = url_for("main.public_view_location", username=username, code=code, _external=True)
    img = qr_label_image(code, human, link, qr_px=300)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ---------------------- SEO / PWA ----------------------

@main_bp.route("/robots.txt")
def robots_txt():
    return Response("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", mimetype="text/plain")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{request.url_root.rstrip('/')}/</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/login</loc></url>
  <url><loc>{request.url_root.rstrip('/')}/register</loc></url>
</urlset>"""
    return Response(xml, mimetype="application/xml")


@main_bp.route("/sw.js")
def service_worker():
    resp = make_response(send_from_directory("static", "sw.js"))
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "application/javascript"
    return resp


@main_bp.route("/offline")
def offline():
    return render_template("offline.html")


# ====================== Impresión etiqueta ======================

def _ellipsize(s: str, n: int = 20) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"

def _build_item_label_pdf(it, settings) -> bytes:
    W = 40 * mm
    H = 30 * mm
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))

    m = 3 * mm
    inner_w = W - 2 * m
    y = H - m

    sku = it.sku or ""
    bc = code128.Code128(sku, barHeight=H * 0.38, humanReadable=False)
    bw, bh = bc.width, bc.height
    scale = min(1.0, inner_w / bw)
    x_bc = m + (inner_w - bw * scale) / 2.0
    y_bc = y - bh * scale
    c.saveState()
    c.translate(x_bc, y_bc)
    c.scale(scale, scale)
    bc.drawOn(c, 0, 0)
    c.restoreState()
    y = y_bc - 2

    title = _ellipsize(it.title or "", 20)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2.0, y - 10, title)
    y -= 14

    loc = it.location_code or "-"
    c.setFont("Helvetica", 8)
    c.drawCentredString(W / 2.0, y - 10, loc)

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()
    return pdf_bytes

@main_bp.route("/item/<int:item_id>/print", methods=["POST"])
@login_required
def print_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    s = get_or_create_settings(current_user)
    pdf_bytes = _build_item_label_pdf(it, s)

    printer_name = os.environ.get("QVENTORY_PRINTER")
    try:
        with tempfile.NamedTemporaryFile(prefix="qventory_label_", suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes); tmp_path = tmp.name

        lp_cmd = ["lp"]
        if printer_name: lp_cmd += ["-d", printer_name]
        lp_cmd.append(tmp_path)

        res = subprocess.run(lp_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            flash("Label sent to printer.", "ok")
            try: os.unlink(tmp_path)
            except Exception: pass
            return redirect(url_for("main.dashboard"))
        else:
            flash("Printing failed. Downloading the label instead.", "error")
            return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                             as_attachment=True, download_name=f"label_{it.sku}.pdf")
    except FileNotFoundError:
        flash("System print not available. Downloading the label.", "error")
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=f"label_{it.sku}.pdf")
    except Exception as e:
        flash(f"Unexpected error: {e}. Downloading the label.", "error")
        return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                         as_attachment=True, download_name=f"label_{it.sku}.pdf")


# ============================================================
# =============  IMPORT MASIVO DESDE eBay  ===================
# ============================================================

FINDING_ENDPOINT = "https://svcs.ebay.com/services/search/FindingService/v1"
FINDING_VERSION = "1.13.0"

def _ebay_find_items_by_seller(seller: str, page: int = 1, entries_per_page: int = 100,
                               site_id: str = "EBAY-US", max_retries: int = 3, backoff_sec: float = 1.5):
    if not EBAY_CLIENT_ID:
        raise RuntimeError("Falta EBAY_CLIENT_ID en .env para Finding API")

    params = {
        "OPERATION-NAME": "findItemsAdvanced",
        "SERVICE-VERSION": FINDING_VERSION,
        "SECURITY-APPNAME": EBAY_CLIENT_ID,
        "RESPONSE-DATA-FORMAT": "JSON",
        "REST-PAYLOAD": "true",
        "paginationInput.entriesPerPage": str(entries_per_page),
        "paginationInput.pageNumber": str(page),
        "GLOBAL-ID": site_id,
        "itemFilter(0).name": "Seller",
        "itemFilter(0).value(0)": seller,
    }
    headers = {
        "X-EBAY-SOA-OPERATION-NAME": "findItemsAdvanced",
        "X-EBAY-SOA-SECURITY-APPNAME": EBAY_CLIENT_ID,
        "X-EBAY-SOA-GLOBAL-ID": site_id,
        "Accept": "application/json",
        "User-Agent": "Qventory/1.0 (+https://qventory.com)",
    }

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.get(FINDING_ENDPOINT, params=params, headers=headers, timeout=20)
            if r.status_code >= 500:
                time.sleep(backoff_sec * attempt); continue
            r.raise_for_status()
            data = r.json()
            resp = (data.get("findItemsAdvancedResponse") or [{}])[0]
            ack = (resp.get("ack", [""])[0]).lower()
            if ack != "success":
                err = (resp.get("errorMessage") or [{}])[0].get("error", [{}])[0]
                msg = f"{err.get('severity', [''])[0]} {err.get('errorId', [''])[0]}: {err.get('message', [''])[0]}"
                raise RuntimeError(f"Finding API error: {msg}")

            pagination = (resp.get("paginationOutput") or [{}])[0]
            total_pages = int((pagination.get("totalPages") or ["1"])[0])

            items_raw = (resp.get("searchResult") or [{}])[0].get("item", []) or []
            items = []
            for it in items_raw:
                title = (it.get("title", [""]) or [""])[0].strip()
                urls = it.get("viewItemURL", [])
                url = (urls[0] if urls else "").strip()
                if title and url:
                    items.append({"title": title, "url": url})
            return total_pages, items

        except requests.HTTPError as e:
            last_exc = e
            if e.response is not None and 400 <= e.response.status_code < 500:
                raise
            time.sleep(backoff_sec * attempt)
        except Exception as e:
            last_exc = e
            time.sleep(backoff_sec * attempt)

    if last_exc:
        raise last_exc
    return 1, []


def _browse_search_by_seller(seller: str, limit: int = 200, offset: int = 0):
    base = _ebay_base()
    token = _get_ebay_app_token()

    params = {
        "q": "*",
        "limit": str(min(max(limit, 1), 200)),
        "offset": str(max(offset, 0)),
        "fieldgroups": "EXTENDED",
        "filter": (
            f"sellers:{{{seller}}},"
            "buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER},"
            "itemLocationRegion:WORLDWIDE"
        ),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "Qventory/1.0 (+https://qventory.com)",
    }
    r = requests.get(f"{base['browse']}/item_summary/search", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    data = r.json()

    items = []
    for it in data.get("itemSummaries", []) or []:
        title = (it.get("title") or "").strip()
        url = (it.get("itemWebUrl") or "").strip()
        if title and url:
            items.append({"title": title, "url": url})

    total = int(data.get("total", 0))
    new_offset = offset + int(params["limit"])
    if new_offset >= total:
        new_offset = None
    return new_offset, items


# --------- NUEVO: Scraper de storefront /str/<store> como último fallback ---------

def _scrape_storefront_items(store_url: str, max_pages: int = 5):
    """
    Lee páginas públicas de un storefront y devuelve [{'title','url'}, ...]
    Soporta paginación con ?_pgn=N. Evita duplicados. Títulos por aria-label/title o texto.
    """
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                       " AppleWebKit/537.36 (KHTML, like Gecko)"
                       " Chrome/124.0.0.0 Safari/537.36"),
        "Accept": "text/html,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,es;q=0.8",
        "Cache-Control": "no-cache",
    }

    base = store_url.rstrip("/")
    seen_urls = set()
    results = []

    def _collect(html: str):
        nonlocal results
        # 1) anchors a /itm/... con aria-label (título frecuente)
        for m in re.finditer(r'<a[^>]+href="(https://www\.ebay\.com/itm/[^"]+)"[^>]*?(?:aria-label|title)="([^"]+)"', html, re.I):
            href = unescape(m.group(1))
            title = unescape(m.group(2)).strip()
            if href not in seen_urls:
                seen_urls.add(href)
                results.append({"title": title or "eBay Item", "url": href})

        # 2) anchors a /itm/... sin aria-label (tomar texto)
        for m in re.finditer(r'<a[^>]+href="(https://www\.ebay\.com/itm/[^"]+)"[^>]*>([^<]{3,120})</a>', html, re.I):
            href = unescape(m.group(1))
            text = unescape(m.group(2)).strip()
            title = text or "eBay Item"
            if href not in seen_urls:
                seen_urls.add(href)
                results.append({"title": title, "url": href})

    for page in range(1, max_pages + 1):
        url = f"{base}?_pgn={page}"
        try:
            r = requests.get(url, headers=headers, timeout=20)
            if r.status_code >= 400:
                break
            _collect(r.text or "")
            # Heurística: si en esta página no hubo nuevos, paramos
            if page > 1 and len(results) == len(seen_urls):
                break
        except Exception:
            break

    return results


def _import_ebay_for_user(user_id: int, seller: str, max_items: int = 500,
                          global_id: str = "EBAY-US", dry: bool = False, source_input: str = ""):
    """
    Intenta importar en capas: Finding -> Browse -> Scraper storefront.
    Devuelve métricas y (en dry) preview.
    """
    created = 0
    skipped = 0
    seen = 0
    preview = []

    # 1) Finding API
    use_browse_fallback = False
    try:
        page = 1
        per_page = 100
        while seen < max_items:
            total_pages, batch = _ebay_find_items_by_seller(
                seller, page=page, entries_per_page=per_page, site_id=global_id
            )
            if not batch:
                if page == 1:
                    use_browse_fallback = True
                break

            for it in batch:
                if seen >= max_items:
                    break
                seen += 1
                title = it["title"]; url = it["url"]

                exists = Item.query.filter_by(user_id=user_id, ebay_url=url).first()
                if exists:
                    skipped += 1; continue

                if dry:
                    preview.append({"title": title, "url": url}); continue

                sku = generate_sku()
                db.session.add(Item(
                    user_id=user_id, title=title, sku=sku, ebay_url=url,
                    listing_link=None, web_url=None, amazon_url=None, mercari_url=None,
                    vinted_url=None, poshmark_url=None, depop_url=None,
                    A=None, B=None, S=None, C=None, location_code=None
                ))
                created += 1

            if not dry and created:
                db.session.commit()

            page += 1
            if page > total_pages:
                break

    except Exception:
        use_browse_fallback = True

    # 2) Browse API
    used_scraper = False
    if use_browse_fallback and seen < max_items:
        try:
            offset = 0
            per = min(200, max_items)
            while seen < max_items:
                next_offset, batch = _browse_search_by_seller(
                    seller, limit=min(per, max_items - seen), offset=offset
                )
                if not batch:
                    break

                for it in batch:
                    if seen >= max_items:
                        break
                    seen += 1
                    title = it["title"]; url = it["url"]

                    exists = Item.query.filter_by(user_id=user_id, ebay_url=url).first()
                    if exists:
                        skipped += 1; continue

                    if dry:
                        preview.append({"title": title, "url": url}); continue

                    sku = generate_sku()
                    db.session.add(Item(
                        user_id=user_id, title=title, sku=sku, ebay_url=url,
                        listing_link=None, web_url=None, amazon_url=None, mercari_url=None,
                        vinted_url=None, poshmark_url=None, depop_url=None,
                        A=None, B=None, S=None, C=None, location_code=None
                    ))
                    created += 1

                if not dry and created:
                    db.session.commit()

                if next_offset is None:
                    break
                offset = next_offset
        except Exception:
            used_scraper = True
    else:
        # Si Finding devolvió algo, no usamos scraper; si no devolvió y no queremos Browse, cae a scraper
        if seen == 0:
            used_scraper = True

    # 3) Scraper storefront (si 0 o poco y tenemos un /str/ en la entrada)
    if used_scraper and seen < max_items and source_input and "/str/" in source_input:
        try:
            store_url = source_input
            items = _scrape_storefront_items(store_url, max_pages=6)
            for it in items:
                if seen >= max_items:
                    break
                url = it["url"]; title = it["title"]
                exists = Item.query.filter_by(user_id=user_id, ebay_url=url).first()
                if exists:
                    skipped += 1; continue
                seen += 1
                if dry:
                    preview.append({"title": title, "url": url}); continue
                sku = generate_sku()
                db.session.add(Item(
                    user_id=user_id, title=title, sku=sku, ebay_url=url,
                    listing_link=None, web_url=None, amazon_url=None, mercari_url=None,
                    vinted_url=None, poshmark_url=None, depop_url=None,
                    A=None, B=None, S=None, C=None, location_code=None
                ))
                created += 1
            if not dry and created:
                db.session.commit()
        except Exception:
            pass

    return {
        "seller": seller,
        "created": created,
        "skipped": skipped,
        "seen": seen,
        "preview": preview if dry else None
    }


@main_bp.route("/api/ebay/import-seller", methods=["POST"])
@login_required
def api_ebay_import_seller():
    """
    Body JSON:
      {
        "source": "<username | /usr/... | /str/... URL>",
        "max_items": 500,        # opcional (default 500; tope 2000)
        "site_hint": "EBAY-US",  # opcional
        "dry": false             # opcional; si true, sólo preview
      }
    """
    try:
        payload = request.get_json(silent=True) or {}
        source = (payload.get("source") or "").strip()
        dry = bool(payload.get("dry", False))
        max_items = min(int(payload.get("max_items", 500)), 2000)
        site_hint = (payload.get("site_hint") or "").strip() or None

        if not source:
            return jsonify({"ok": False, "error": "Missing 'source' (username o URL)"}), 400

        seller = _parse_seller_from_input(source)
        if not seller:
            return jsonify({"ok": False, "error": "No se pudo deducir el seller desde 'source'"}), 400

        global_id = site_hint or "EBAY-US"
        if not site_hint:
            try:
                if re.match(r"^https?://", source, re.I):
                    global_id = _normalize_site_id(urlparse(source).netloc)
            except Exception:
                pass

        result = _import_ebay_for_user(current_user.id, seller, max_items=max_items,
                                       global_id=global_id, dry=dry, source_input=source)
        return jsonify({"ok": True, **result})
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response is not None else ""
        return jsonify({"ok": False, "error": f"HTTP {e.response.status_code}: {body}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# -------------- UI: Importar desde eBay (form + preview + import) --------------

@main_bp.route("/import/ebay", methods=["GET", "POST"])
@login_required
def import_ebay():
    context = {"source": "", "site_hint": "", "max_items": 500, "preview": None, "stats": None}

    if request.method == "POST":
        action = (request.form.get("action") or "preview").strip()
        source = (request.form.get("source") or "").strip()
        site_hint = (request.form.get("site_hint") or "").strip()
        try:
            max_items = int(request.form.get("max_items") or 500)
        except ValueError:
            max_items = 500
        max_items = max(1, min(max_items, 2000))
        context.update({"source": source, "site_hint": site_hint, "max_items": max_items})

        if not source:
            flash("Please provide an eBay username or store/account URL.", "error")
            return render_template("import_ebay.html", **context)

        seller = _parse_seller_from_input(source)
        if not seller:
            flash("Could not resolve a valid eBay seller from the provided input.", "error")
            return render_template("import_ebay.html", **context)

        global_id = site_hint or "EBAY-US"
        if not site_hint and re.match(r"^https?://", source, re.I):
            try:
                global_id = _normalize_site_id(urlparse(source).netloc)
            except Exception:
                pass

        dry = (action == "preview")
        try:
            result = _import_ebay_for_user(current_user.id, seller, max_items=max_items,
                                           global_id=global_id, dry=dry, source_input=source)
        except Exception as e:
            flash(f"Error importing from eBay: {e}", "error")
            return render_template("import_ebay.html", **context)

        if dry:
            context["preview"] = result.get("preview") or []
            flash(f"Preview ready for seller '{seller}'. ({len(context['preview'])} items)", "ok")
        else:
            context["stats"] = {
                "seller": seller,
                "created": result.get("created"),
                "skipped": result.get("skipped"),
                "seen": result.get("seen"),
                "global_id": global_id
            }
            if result.get("created", 0) == 0 and result.get("seen", 0) == 0 and "/str/" in source:
                flash("APIs devolvieron 0; se intentó scraping del storefront automáticamente.", "error")
            else:
                flash(f"Imported {result.get('created')} item(s). Skipped {result.get('skipped')}.", "ok")

    return render_template("import_ebay.html", **context)


# --------- Ruta opcional de depuración para ver qué pasó en cada capa ---------

@main_bp.route("/api/ebay/debug")
@login_required
def ebay_debug():
    source = (request.args.get("source") or "").strip()
    site_hint = (request.args.get("site_hint") or "").strip() or None
    if not source:
        return jsonify({"ok": False, "error": "Missing source"}), 400
    seller = _parse_seller_from_input(source) or ""
    global_id = site_hint or "EBAY-US"
    if not site_hint and re.match(r"^https?://", source, re.I):
        try:
            global_id = _normalize_site_id(urlparse(source).netloc)
        except Exception:
            pass

    info = {"source": source, "seller_resolved": seller, "global_id": global_id, "finding_count": None, "browse_count": None, "scrape_count": None}

    # quick probes (no creación, solo contar)
    try:
        _, items = _ebay_find_items_by_seller(seller, page=1, entries_per_page=50, site_id=global_id)
        info["finding_count"] = len(items)
    except Exception as e:
        info["finding_count"] = f"error: {e}"

    try:
        _, items = _browse_search_by_seller(seller, limit=50, offset=0)
        info["browse_count"] = len(items)
    except Exception as e:
        info["browse_count"] = f"error: {e}"

    if "/str/" in source:
        try:
            items = _scrape_storefront_items(source, max_pages=2)
            info["scrape_count"] = len(items)
        except Exception as e:
            info["scrape_count"] = f"error: {e}"

    return jsonify({"ok": True, "probe": info})
