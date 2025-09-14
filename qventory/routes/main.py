from flask import (
    render_template, request, redirect, url_for, send_file, flash, Response,
    jsonify, send_from_directory, make_response
)
from flask_login import login_required, current_user
from sqlalchemy import or_
import io
import re
import os
import tempfile
import subprocess
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm

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
    # Página pública de marketing/SEO
    return render_template("landing.html")


# ---------------------- Dashboard (protegido) ----------------------

@main_bp.route("/dashboard")
@login_required
def dashboard():
    s = get_or_create_settings(current_user)

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

    # Filtros de ubicación (solo niveles habilitados)
    if s.enable_A and fA:
        items = items.filter(Item.A == fA)
    if s.enable_B and fB:
        items = items.filter(Item.B == fB)
    if s.enable_S and fS:
        items = items.filter(Item.S == fS)
    if s.enable_C and fC:
        items = items.filter(Item.C == fC)

    # Filtro por plataforma (si el item tiene URL para esa plataforma)
    if fPlatform:
        col = {
            "web": Item.web_url, "ebay": Item.ebay_url, "amazon": Item.amazon_url,
            "mercari": Item.mercari_url, "vinted": Item.vinted_url,
            "poshmark": Item.poshmark_url, "depop": Item.depop_url
        }.get(fPlatform)
        if col is not None:
            items = items.filter(col.isnot(None))

    items = items.order_by(Item.created_at.desc()).all()

    # Distintos por columna, scope por usuario
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
        items=items, settings=s, options=options,
        q=q, fA=fA, fB=fB, fS=fS, fC=fC,
        fPlatform=fPlatform, PLATFORMS=PLATFORMS
    )


# ---------------------- Helpers scraping / anti-bot eBay ----------------------

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
)

def _make_session():
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

def _fetch_html_with_cookies(url, ua, timeout=20):
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Dest": "document",
    }
    sess = _make_session()

    # 1) Primer GET: eBay puede plantar cookies y devolver content-length: 1
    r1 = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    r1.raise_for_status()
    text = r1.text or ""

    # 2) Si el body es muy corto, hacer segundo GET con cookies ya plantadas
    if len(text) < 1000:
        r2 = sess.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        r2.raise_for_status()
        text = r2.text or ""

    return text

def _extract_title_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.select_one("h1.x-item-title__mainTitle")
    if h1:
        return h1.get_text(strip=True)
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    ttag = soup.find("title")
    if ttag and ttag.get_text(strip=True):
        return ttag.get_text(strip=True)
    return None


# ---------------------- API helper: importar título desde URL ----------------------

@main_bp.route("/api/fetch-market-title")
@login_required
def api_fetch_market_title():
    """
    Recibe ?url=... , detecta marketplace y devuelve {ok, marketplace, title, fill: {...}}
    Soporta eBay: busca h1.x-item-title__mainTitle y fallbacks og:title y <title>.
    Implementa sesión/cookies, retries y fallback a UA móvil para saltar anti-bot.
    """
    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "Missing url"}), 400

    if not re.match(r"^https?://", raw_url, re.I):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    try:
        netloc = urlparse(raw_url).netloc.lower()
    except Exception:
        netloc = ""

    is_ebay = any(
        netloc.endswith(d)
        for d in [
            "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr", "ebay.it",
            "ebay.es", "ebay.ca", "ebay.com.au", "ebay.com.mx",
            "ebay.com.sg", "ebay.com.hk", "ebay.nl"
        ]
    )
    marketplace = "ebay" if is_ebay else "unknown"

    title_text = None

    if marketplace == "ebay":
        try:
            html = _fetch_html_with_cookies(raw_url, DESKTOP_UA, timeout=20)
            title_text = _extract_title_from_html(html)

            if not title_text or len(html) < 1000:
                html_m = _fetch_html_with_cookies(raw_url, MOBILE_UA, timeout=20)
                maybe = _extract_title_from_html(html_m)
                if maybe:
                    title_text = maybe

            if not title_text:
                return jsonify({"ok": False, "error": "No se pudo extraer el título de eBay."}), 502

        except requests.exceptions.Timeout:
            return jsonify({"ok": False, "error": "Timeout: eBay no respondió a tiempo"}), 504
        except requests.exceptions.RequestException as e:
            return jsonify({"ok": False, "error": f"Request/parse failed: {e}"}), 502

    fill = {}
    if title_text:
        fill["title"] = title_text
    if marketplace == "ebay":
        fill["ebay_url"] = raw_url

    return jsonify({
        "ok": True,
        "marketplace": marketplace,
        "title": title_text,
        "fill": fill
    })


# ---------------------- CRUD Items (protegido) ----------------------

@main_bp.route("/item/new", methods=["GET", "POST"])
@login_required
def new_item():
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
            return redirect(url_for("main.new_item"))

        sku = generate_sku()
        loc = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        it = Item(
            user_id=current_user.id,
            title=title, sku=sku, listing_link=listing_link,
            web_url=web_url, ebay_url=ebay_url, amazon_url=amazon_url,
            mercari_url=mercari_url, vinted_url=vinted_url,
            poshmark_url=poshmark_url, depop_url=depop_url,
            A=A, B=B, S=S_, C=C, location_code=loc
        )
        db.session.add(it)
        db.session.commit()
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


# ---------------------- Print label (protegido) ----------------------

def _ellipsize(s: str, n: int = 20) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"

def _build_item_label_pdf(it, settings) -> bytes:
    """
    PDF 40x30mm:
      - Code128 (SKU)
      - Título (20 chars + …)
      - Ubicación (location_code)
    """
    W = 40 * mm
    H = 30 * mm

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))

    m = 3 * mm
    inner_w = W - 2 * m
    y = H - m

    # Barcode SKU
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

    # Título
    title = _ellipsize(it.title or "", 20)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2.0, y - 10, title)
    y = y - 14

    # Ubicación
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

    printer_name = os.environ.get("QVENTORY_PRINTER")  # opcional
    try:
        with tempfile.NamedTemporaryFile(prefix="qventory_label_", suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        lp_cmd = ["lp"]
        if printer_name:
            lp_cmd += ["-d", printer_name]
        lp_cmd.append(tmp_path)

        res = subprocess.run(lp_cmd, capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            flash("Label sent to printer.", "ok")
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return redirect(url_for("main.dashboard"))
        else:
            flash("Printing failed. Downloading the label instead.", "error")
            return send_file(
                io.BytesIO(pdf_bytes),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"label_{it.sku}.pdf",
            )
    except FileNotFoundError:
        flash("System print not available. Downloading the label.", "error")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"label_{it.sku}.pdf",
        )
    except Exception as e:
        flash(f"Unexpected error: {e}. Downloading the label.", "error")
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"label_{it.sku}.pdf",
        )


# ---------------------- Batch QR (protegido) ----------------------

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


# ---------------------- SEO / PWA extra ----------------------

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
