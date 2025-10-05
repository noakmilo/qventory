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
from urllib.parse import urlparse, parse_qs
import csv
from datetime import datetime, date

# Dotenv: carga credenciales/vars desde /opt/qventory/qventory/.env
from dotenv import load_dotenv
load_dotenv("/opt/qventory/qventory/.env")

# >>> IMPRESIÓN (lo existente + QR)
import tempfile
import subprocess
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
import qrcode
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

# ==================== Cloudinary ====================
# pip install cloudinary
CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")
CLOUDINARY_UPLOAD_FOLDER = os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "qventory/items")

cloudinary_enabled = bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)

if cloudinary_enabled:
    try:
        import cloudinary
        import cloudinary.uploader
        cloudinary.config(
            cloud_name=CLOUDINARY_CLOUD_NAME,
            api_key=CLOUDINARY_API_KEY,
            api_secret=CLOUDINARY_API_SECRET,
            secure=True
        )
    except Exception as _e:
        cloudinary_enabled = False


# ---------------------- Landing pública ----------------------

@main_bp.route("/")
def landing():
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

    items_query = Item.query.filter_by(user_id=current_user.id)

    if q:
        like = f"%{q}%"
        items_query = items_query.filter(or_(Item.title.ilike(like), Item.sku.ilike(like)))

    if s.enable_A and fA:
        items_query = items_query.filter(Item.A == fA)
    if s.enable_B and fB:
        items_query = items_query.filter(Item.B == fB)
    if s.enable_S and fS:
        items_query = items_query.filter(Item.S == fS)
    if s.enable_C and fC:
        items_query = items_query.filter(Item.C == fC)

    if fPlatform:
        col = {
            "web": Item.web_url, "ebay": Item.ebay_url, "amazon": Item.amazon_url,
            "mercari": Item.mercari_url, "vinted": Item.vinted_url,
            "poshmark": Item.poshmark_url, "depop": Item.depop_url
        }.get(fPlatform)
        if col is not None:
            items_query = items_query.filter(col.isnot(None))

    items_query = items_query.order_by(Item.created_at.desc())
    total_items = items_query.count()

    # Solo cargar los primeros 20 items
    items = items_query.limit(20).all()

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


# ---------------------- API: Load more items (infinite scroll) ----------------------

@main_bp.route("/api/load-more-items")
@login_required
def api_load_more_items():
    s = get_or_create_settings(current_user)

    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 20))

    q = (request.args.get("q") or "").strip()
    fA = (request.args.get("A") or "").strip()
    fB = (request.args.get("B") or "").strip()
    fS = (request.args.get("S") or "").strip()
    fC = (request.args.get("C") or "").strip()
    fPlatform = (request.args.get("platform") or "").strip()

    items_query = Item.query.filter_by(user_id=current_user.id)

    if q:
        like = f"%{q}%"
        items_query = items_query.filter(or_(Item.title.ilike(like), Item.sku.ilike(like)))

    if s.enable_A and fA:
        items_query = items_query.filter(Item.A == fA)
    if s.enable_B and fB:
        items_query = items_query.filter(Item.B == fB)
    if s.enable_S and fS:
        items_query = items_query.filter(Item.S == fS)
    if s.enable_C and fC:
        items_query = items_query.filter(Item.C == fC)

    if fPlatform:
        col = {
            "web": Item.web_url, "ebay": Item.ebay_url, "amazon": Item.amazon_url,
            "mercari": Item.mercari_url, "vinted": Item.vinted_url,
            "poshmark": Item.poshmark_url, "depop": Item.depop_url
        }.get(fPlatform)
        if col is not None:
            items_query = items_query.filter(col.isnot(None))

    items = items_query.order_by(Item.created_at.desc()).offset(offset).limit(limit).all()

    # Renderizar solo las filas de items
    from flask import render_template_string

    items_html = []
    for it in items:
        # Generar HTML para cada item (usando el mismo formato del dashboard)
        item_html = render_template("_item_row.html", item=it, settings=s)
        items_html.append(item_html)

    return jsonify({
        "ok": True,
        "items": items_html,
        "has_more": len(items) == limit
    })


# ---------------------- CSV Export/Import (protegido) ----------------------

@main_bp.route("/export/csv")
@login_required
def export_csv():
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.created_at.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'id', 'sku', 'title', 'listing_link',
        'web_url', 'ebay_url', 'amazon_url', 'mercari_url', 'vinted_url', 'poshmark_url', 'depop_url',
        'A', 'B', 'S', 'C', 'location_code',
        # nuevos
        'item_thumb', 'supplier', 'item_cost', 'item_price', 'listing_date',
        'created_at'
    ]
    writer.writerow(headers)

    for it in items:
        row = [
            it.id,
            it.sku,
            it.title,
            it.listing_link or '',
            it.web_url or '',
            it.ebay_url or '',
            it.amazon_url or '',
            it.mercari_url or '',
            it.vinted_url or '',
            it.poshmark_url or '',
            it.depop_url or '',
            it.A or '',
            it.B or '',
            it.S or '',
            it.C or '',
            it.location_code or '',
            it.item_thumb or '',
            it.supplier or '',
            f"{it.item_cost:.2f}" if it.item_cost is not None else '',
            f"{it.item_price:.2f}" if it.item_price is not None else '',
            it.listing_date.strftime('%Y-%m-%d') if isinstance(it.listing_date, (date, datetime)) and it.listing_date else '',
            it.created_at.strftime('%Y-%m-%d %H:%M:%S') if it.created_at else ''
        ]
        writer.writerow(row)

    output.seek(0)
    csv_data = output.getvalue().encode('utf-8')
    output.close()

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"qventory_backup_{current_user.username}_{timestamp}.csv"

    return send_file(
        io.BytesIO(csv_data),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# ===== CSV Import Helpers =====

def _detect_csv_format(fieldnames):
    """
    Detecta el formato del CSV:
    - 'qventory': formato nativo de Qventory (tiene 'sku' y 'title')
    - 'flipwise': formato de Flipwise/otras plataformas (tiene 'Product', 'Cost', 'List price', etc.)
    - 'unknown': formato desconocido
    """
    fieldnames_lower = [f.lower().strip() for f in fieldnames]

    # Formato Qventory: debe tener 'sku' y 'title'
    if 'sku' in fieldnames_lower and 'title' in fieldnames_lower:
        return 'qventory'

    # Formato Flipwise/similar: tiene 'Product' o 'product' y otros campos característicos
    if 'product' in fieldnames_lower:
        return 'flipwise'

    return 'unknown'


def _parse_external_row_to_qventory(row, user_id):
    """
    Convierte una fila de CSV externo (Flipwise, etc.) al formato de Qventory.

    Mapeo de campos:
    - Product -> title
    - Cost -> item_cost
    - List price -> item_price
    - Purchased at -> supplier
    - eBay Item ID -> ebay_url (si existe)
    - Genera SKU automáticamente
    - Usa fecha actual como listing_date
    - Ignora location (usuario lo define después)
    """
    # Helpers
    def fstr(key):
        val = row.get(key, '')
        if isinstance(val, str):
            return val.strip() or None
        return str(val).strip() if val else None

    def ffloat(key):
        val = fstr(key)
        if not val:
            return None
        try:
            return float(val.replace(',', ''))
        except:
            return None

    # Extraer datos del CSV externo
    title = fstr('Product') or fstr('product') or fstr('Title') or fstr('title')
    if not title:
        return None

    # Generar SKU automático usando el helper de Qventory
    sku = generate_sku()

    # Mapear campos
    cost = ffloat('Cost') or ffloat('cost')
    price = ffloat('List price') or ffloat('list price') or ffloat('List Price')
    supplier = fstr('Purchased at') or fstr('purchased at')

    # eBay Item ID -> construir URL de eBay
    ebay_item_id = fstr('eBay Item ID') or fstr('ebay item id')
    ebay_url = f"https://www.ebay.com/itm/{ebay_item_id}" if ebay_item_id else None

    # Usar fecha actual como listing_date (ignoramos las fechas del CSV externo)
    listing_date = date.today()

    return {
        'sku': sku,
        'title': title,
        'item_cost': cost,
        'item_price': price,
        'supplier': supplier,
        'ebay_url': ebay_url,
        'listing_date': listing_date,
        # Campos que se ignoran (usuario los define después)
        'A': None,
        'B': None,
        'S': None,
        'C': None,
        'location_code': None,
        'listing_link': None,
        'web_url': None,
        'amazon_url': None,
        'mercari_url': None,
        'vinted_url': None,
        'poshmark_url': None,
        'depop_url': None,
        'item_thumb': None
    }


def _parse_qventory_row(row):
    """Parse una fila del formato nativo de Qventory"""
    def fstr(k):
        return (row.get(k) or '').strip() or None

    def ffloat(k):
        v = (row.get(k) or '').strip()
        try:
            return float(v) if v != '' else None
        except:
            return None

    def fdate(k):
        v = (row.get(k) or '').strip()
        if not v:
            return None
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
            try:
                dt = datetime.strptime(v, fmt)
                return dt.date() if fmt == "%Y-%m-%d" else dt
            except:
                pass
        return None

    sku = fstr('sku')
    title = fstr('title')

    if not sku or not title:
        return None

    ld = fdate('listing_date')

    return {
        'sku': sku,
        'title': title,
        'listing_link': fstr('listing_link'),
        'web_url': fstr('web_url'),
        'ebay_url': fstr('ebay_url'),
        'amazon_url': fstr('amazon_url'),
        'mercari_url': fstr('mercari_url'),
        'vinted_url': fstr('vinted_url'),
        'poshmark_url': fstr('poshmark_url'),
        'depop_url': fstr('depop_url'),
        'A': fstr('A'),
        'B': fstr('B'),
        'S': fstr('S'),
        'C': fstr('C'),
        'location_code': fstr('location_code'),
        'item_thumb': fstr('item_thumb'),
        'supplier': fstr('supplier'),
        'item_cost': ffloat('item_cost'),
        'item_price': ffloat('item_price'),
        'listing_date': ld if isinstance(ld, date) else None
    }


@main_bp.route("/import/csv", methods=["GET", "POST"])
@login_required
def import_csv():
    if request.method == "GET":
        return render_template("import_csv.html")

    if 'csv_file' not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for('main.import_csv'))

    file = request.files['csv_file']
    if file.filename == '' or not file.filename.lower().endswith('.csv'):
        flash("Please select a valid CSV file.", "error")
        return redirect(url_for('main.import_csv'))

    mode = request.form.get('import_mode', 'add')

    try:
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))

        # Detectar formato del CSV
        csv_format = _detect_csv_format(csv_reader.fieldnames)

        if csv_format == 'unknown':
            flash("CSV format not recognized. Please use Qventory format or supported external formats (Flipwise).", "error")
            return redirect(url_for('main.import_csv'))

        imported_count = 0
        updated_count = 0
        skipped_count = 0
        duplicate_count = 0

        # Set para detectar duplicados por título
        seen_titles = set()
        existing_titles = {item.title.lower().strip() for item in Item.query.filter_by(user_id=current_user.id).all()}

        for row in csv_reader:
            # Parsear según el formato detectado
            if csv_format == 'qventory':
                parsed_data = _parse_qventory_row(row)
            elif csv_format == 'flipwise':
                parsed_data = _parse_external_row_to_qventory(row, current_user.id)
            else:
                skipped_count += 1
                continue

            if not parsed_data:
                skipped_count += 1
                continue

            # Detectar duplicados exactos por título
            title_normalized = parsed_data['title'].lower().strip()

            # Si el título ya existe en la BD o en este mismo CSV, saltar
            if title_normalized in existing_titles or title_normalized in seen_titles:
                duplicate_count += 1
                continue

            seen_titles.add(title_normalized)

            sku = parsed_data['sku']
            existing_item = Item.query.filter_by(user_id=current_user.id, sku=sku).first()

            if existing_item and mode == 'add':
                # Actualizar item existente
                for key, value in parsed_data.items():
                    if key != 'sku':  # No actualizar el SKU
                        setattr(existing_item, key, value)
                updated_count += 1

            elif not existing_item:
                # Crear nuevo item
                new_item = Item(user_id=current_user.id, **parsed_data)
                db.session.add(new_item)
                imported_count += 1
                # Agregar a existing_titles para prevenir duplicados en el mismo CSV
                existing_titles.add(title_normalized)

        if mode == 'replace':
            # En modo replace, eliminar items que no están en el CSV
            csv_skus = {parsed_data['sku'] for parsed_data in
                       [_parse_qventory_row(r) if csv_format == 'qventory' else _parse_external_row_to_qventory(r, current_user.id)
                        for r in csv.DictReader(io.StringIO(csv_content))]
                       if parsed_data}
            items_to_delete = Item.query.filter_by(user_id=current_user.id).filter(~Item.sku.in_(csv_skus)).all()
            for item in items_to_delete:
                db.session.delete(item)

        db.session.commit()

        messages = []
        messages.append(f"Format detected: {csv_format.upper()}")
        if imported_count > 0:
            messages.append(f"{imported_count} items imported")
        if updated_count > 0:
            messages.append(f"{updated_count} items updated")
        if duplicate_count > 0:
            messages.append(f"{duplicate_count} duplicates skipped")
        if skipped_count > 0:
            messages.append(f"{skipped_count} rows skipped")

        flash(f"Import completed: {', '.join(messages)}.", "ok")

    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {str(e)}", "error")

    return redirect(url_for('main.dashboard'))


# ---------------------- eBay Browse API ----------------------

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
    data = { "grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope" }
    headers = { "Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Basic {basic}" }
    r = requests.post(base["oauth"], headers=headers, data=data, timeout=15)
    r.raise_for_status()
    j = r.json()
    _EBAY_TOKEN["value"] = j["access_token"]
    _EBAY_TOKEN["exp"] = now + int(j.get("expires_in", 7200))
    return _EBAY_TOKEN["value"]


# ---------------------- Utilidades URL eBay ----------------------

_EBAY_HOSTS = (
    "ebay.com", "www.ebay.com", "m.ebay.com",
    "ebay.co.uk", "www.ebay.co.uk", "m.ebay.co.uk",
    "ebay.ca", "www.ebay.ca", "m.ebay.ca",
)

def _looks_like_ebay_store_or_search(path: str) -> bool:
    return bool(re.match(r"^/(?:str|sch|b)/", path, re.I))

def _extract_legacy_id(url: str) -> str | None:
    try:
        u = urlparse(url)
        path = u.path or ""
        if _looks_like_ebay_store_or_search(path):
            return None
        rx_list = [
            r"/itm/(?:[^/]+/)?(\d{9,})",
            r"/itm/(\d{9,})",
            r"/(\d{12})(?:[/?]|$)",
        ]
        for rx in rx_list:
            m = re.search(rx, path)
            if m:
                return m.group(1)
        qs = parse_qs(u.query)
        for key in ("item", "iid", "itemid", "legacyItemId", "itemId"):
            vals = qs.get(key)
            if vals and len(vals) > 0:
                m = re.search(r"\d{9,}", vals[0])
                if m:
                    return m.group(0)
        m = re.search(r"(\d{12,})", url)
        return m.group(1) if m else None
    except Exception:
        return None


# ---------------------- API helper eBay ----------------------

@main_bp.route("/api/fetch-market-title")
@login_required
def api_fetch_market_title():
    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "Missing url"}), 400
    if not re.match(r"^https?://", raw_url, re.I):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    u = urlparse(raw_url)
    host = (u.netloc or "").lower()
    path = u.path or ""

    if any(host.endswith(h) for h in _EBAY_HOSTS) and _looks_like_ebay_store_or_search(path):
        return jsonify({
            "ok": False,
            "error": "La URL de eBay parece de tienda/búsqueda/categoría. Proporciona el enlace directo del producto (/itm/...)."
        }), 400

    legacy_id = _extract_legacy_id(raw_url)
    if not legacy_id:
        return jsonify({
            "ok": False,
            "error": "No se pudo extraer el legacy_item_id. Asegúrate de usar una URL de ítem de eBay (/itm/...)."
        }), 400

    base = _ebay_base()
    try:
        token = _get_ebay_app_token()
        r = requests.get(
            f"{base['browse']}/item/get_item_by_legacy_id",
            params={"legacy_item_id": legacy_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=15
        )

        if r.status_code == 403:
            return jsonify({
                "ok": False,
                "error": f"403 Forbidden: la app no tiene acceso a Browse API en {EBAY_ENV} (o keyset deshabilitado)."
            }), 403
        if r.status_code == 404:
            return jsonify({ "ok": False, "error": "404: legacy_item_id no encontrado por Browse API en este entorno." }), 404

        r.raise_for_status()
        data = r.json()
        title = (data.get("title") or "").strip()
        item_web_url = (data.get("itemWebUrl") or raw_url).strip()
        if not title:
            return jsonify({"ok": False, "error": "La Browse API no devolvió título para este ítem."}), 502

        return jsonify({
            "ok": True,
            "marketplace": "ebay",
            "title": title,
            "fill": {"title": title, "ebay_url": item_web_url}
        })
    except requests.HTTPError as e:
        body = e.response.text[:300] if e.response is not None else ""
        code = e.response.status_code if e.response is not None else 502
        return jsonify({"ok": False, "error": f"HTTP {code}: {body}"}), code
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- API: Upload imagen a Cloudinary ----------------------

@main_bp.route("/api/upload-image", methods=["POST"])
@login_required
def api_upload_image():
    if not cloudinary_enabled:
        return jsonify({"ok": False, "error": "Cloudinary not configured"}), 503

    f = request.files.get("file")
    if not f:
        return jsonify({"ok": False, "error": "Missing file"}), 400

    # Validación simple
    ct = (f.mimetype or "").lower()
    if not ct.startswith("image/"):
        return jsonify({"ok": False, "error": "Only image files are allowed"}), 400

    # Opcional: límite de ~8 MB
    f.seek(0, io.SEEK_END)
    size = f.tell()
    f.seek(0)
    if size > 8 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image too large (max 8MB)"}), 400

    try:
        up = cloudinary.uploader.upload(
            f,
            folder=CLOUDINARY_UPLOAD_FOLDER,
            overwrite=True,
            resource_type="image",
            transformation=[{"quality": "auto", "fetch_format": "auto"}]
        )
        url = up.get("secure_url") or up.get("url")
        public_id = up.get("public_id")
        width = up.get("width")
        height = up.get("height")
        return jsonify({"ok": True, "url": url, "public_id": public_id, "width": width, "height": height})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- CRUD Items (protegido) ----------------------

def _parse_float(s: str | None):
    if s is None or s == "":
        return None
    try:
        return float(s)
    except:
        return None

def _parse_date(s: str | None):
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(s, fmt).date()
        except:
            pass
    return None

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

        # Nuevos campos
        item_thumb  = (request.form.get("item_thumb") or "").strip() or None
        supplier    = (request.form.get("supplier") or "").strip() or None
        item_cost   = _parse_float(request.form.get("item_cost"))
        item_price  = _parse_float(request.form.get("item_price"))
        listing_date= _parse_date(request.form.get("listing_date"))

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
            user_id=current_user.id,
            title=title,
            sku=sku,
            listing_link=listing_link,
            web_url=web_url, ebay_url=ebay_url, amazon_url=amazon_url,
            mercari_url=mercari_url, vinted_url=vinted_url, poshmark_url=poshmark_url, depop_url=depop_url,
            A=A, B=B, S=S_, C=C, location_code=loc,
            # nuevos
            item_thumb=item_thumb, supplier=supplier, item_cost=item_cost, item_price=item_price, listing_date=listing_date
        )
        db.session.add(it)
        db.session.commit()

        action = (request.form.get("submit_action") or "create").strip()
        if action == "create_another":
            flash("Item created. You can add another.", "ok")
            return render_template("new_item.html", settings=s, item=None, cloudinary_enabled=cloudinary_enabled)

        flash("Item created.", "ok")
        return redirect(url_for("main.dashboard"))

    return render_template("new_item.html", settings=s, item=None, cloudinary_enabled=cloudinary_enabled)


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

        # Nuevos campos
        item_thumb  = (request.form.get("item_thumb") or "").strip() or None
        supplier    = (request.form.get("supplier") or "").strip() or None
        item_cost   = _parse_float(request.form.get("item_cost"))
        item_price  = _parse_float(request.form.get("item_price"))
        listing_date= _parse_date(request.form.get("listing_date"))

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

        it.item_thumb = item_thumb
        it.supplier = supplier
        it.item_cost = item_cost
        it.item_price = item_price
        it.listing_date = listing_date

        it.A, it.B, it.S, it.C = A, B, S_, C
        it.location_code = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        db.session.commit()
        flash("Item updated.", "ok")
        return redirect(url_for("main.dashboard"))
    return render_template("edit_item.html", item=it, settings=s, cloudinary_enabled=cloudinary_enabled)


@main_bp.route("/item/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    it = Item.query.filter_by(id=item_id, user_id=current_user.id).first_or_404()
    db.session.delete(it)
    db.session.commit()
    flash("Item deleted.", "ok")
    return redirect(url_for("main.dashboard"))


# ---------------------- Settings (protegido) ----------------------

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


# ====================== helpers + ruta de IMPRESIÓN con QR ======================

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
    inner_h = H - 2 * m

    title_fs = 8
    loc_fs = 8
    leading = 1.2
    title_h = title_fs * leading
    loc_h = loc_fs * leading

    gap_qr_title = 1.5 * mm
    gap_title_loc = 0.8 * mm

    qr_size = 15 * mm

    block_h = qr_size + gap_qr_title + title_h + gap_title_loc + loc_h
    y0 = m + (inner_h - block_h) / 2.0

    sku = it.sku or ""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(sku)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    if getattr(qr_img, "mode", None) != 'RGB':
        qr_img = qr_img.convert('RGB')
    x_qr = m + (inner_w - qr_size) / 2.0
    c.drawImage(ImageReader(qr_img), x_qr, y0, width=qr_size, height=qr_size, preserveAspectRatio=True)

    title = _ellipsize(it.title or "", 20)
    c.setFont("Helvetica-Bold", title_fs)
    y_title = y0 + qr_size + gap_qr_title + title_fs
    c.drawCentredString(W / 2.0, y_title, title)

    loc = it.location_code or "-"
    c.setFont("Helvetica", loc_fs)
    y_loc = y0 + qr_size + gap_qr_title + title_h + gap_title_loc + loc_fs
    c.drawCentredString(W / 2.0, y_loc, loc)

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


# ==================== ADMIN BACKOFFICE ====================

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

def check_admin_auth():
    """Check if admin is authenticated via session"""
    return request.cookies.get("admin_auth") == "authenticated"

def require_admin():
    """Decorator to require admin authentication"""
    if not check_admin_auth():
        return redirect(url_for('main.admin_login'))
    return None


@main_bp.route("/admin")
def admin_redirect():
    """Redirect /admin to /admin/login"""
    return redirect(url_for('main.admin_login'))


@main_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    """Admin login page"""
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            resp = make_response(redirect(url_for('main.admin_dashboard')))
            resp.set_cookie('admin_auth', 'authenticated', max_age=3600*24)  # 24 hours
            flash("Admin authentication successful", "ok")
            return resp
        else:
            flash("Invalid admin password", "error")

    return render_template("admin_login.html")


@main_bp.route("/admin/logout")
def admin_logout():
    """Admin logout"""
    resp = make_response(redirect(url_for('main.admin_login')))
    resp.set_cookie('admin_auth', '', expires=0)
    flash("Logged out from admin", "ok")
    return resp


@main_bp.route("/admin/dashboard")
def admin_dashboard():
    """Admin dashboard - view all users and their inventory stats"""
    auth_check = require_admin()
    if auth_check:
        return auth_check

    # Get all users with item count
    users = User.query.all()
    user_stats = []

    for user in users:
        item_count = Item.query.filter_by(user_id=user.id).count()
        user_stats.append({
            'user': user,
            'item_count': item_count,
            'has_inventory': item_count > 0
        })

    # Sort by item count descending
    user_stats.sort(key=lambda x: x['item_count'], reverse=True)

    return render_template("admin_dashboard.html", user_stats=user_stats)


@main_bp.route("/admin/user/<int:user_id>/delete", methods=["POST"])
def admin_delete_user(user_id):
    """Delete a user and all their items"""
    auth_check = require_admin()
    if auth_check:
        return auth_check

    user = User.query.get_or_404(user_id)
    username = user.username

    # Delete all items belonging to this user
    Item.query.filter_by(user_id=user_id).delete()

    # Delete user settings
    Setting.query.filter_by(user_id=user_id).delete()

    # Delete the user
    db.session.delete(user)
    db.session.commit()

    flash(f"User '{username}' and all their data deleted successfully", "ok")
    return redirect(url_for('main.admin_dashboard'))


@main_bp.route("/admin/user/create", methods=["GET", "POST"])
def admin_create_user():
    """Create a new user from admin panel"""
    auth_check = require_admin()
    if auth_check:
        return auth_check

    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required", "error")
            return render_template("admin_create_user.html")

        # Check if user already exists
        if User.query.filter_by(username=username).first():
            flash("Username already exists", "error")
            return render_template("admin_create_user.html")

        if User.query.filter_by(email=email).first():
            flash("Email already exists", "error")
            return render_template("admin_create_user.html")

        # Create new user
        from werkzeug.security import generate_password_hash
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()

        flash(f"User '{username}' created successfully", "ok")
        return redirect(url_for('main.admin_dashboard'))

    return render_template("admin_create_user.html")


# ==================== PRIVACY POLICY ====================

@main_bp.route("/privacy")
def privacy_policy():
    """Privacy policy page - compliant with eBay, Poshmark, Mercari, Depop APIs"""
    return render_template("privacy.html")


# ==================== PROFIT CALCULATOR ====================

@main_bp.route("/profit-calculator")
@login_required
def profit_calculator():
    """Standalone profit calculator page"""
    return render_template("profit_calculator.html")


@main_bp.route("/api/autocomplete-items")
@login_required
def api_autocomplete_items():
    """Autocomplete items by title for profit calculator"""
    q = (request.args.get("q") or "").strip()
    if not q or len(q) < 2:
        return jsonify({"ok": True, "items": []})

    like = f"%{q}%"
    items = Item.query.filter_by(user_id=current_user.id)\
        .filter(Item.title.ilike(like))\
        .order_by(Item.created_at.desc())\
        .limit(10).all()

    results = []
    for it in items:
        results.append({
            "id": it.id,
            "title": it.title,
            "sku": it.sku,
            "cost": float(it.item_cost) if it.item_cost is not None else None,
            "price": float(it.item_price) if it.item_price is not None else None,
            "supplier": it.supplier
        })

    return jsonify({"ok": True, "items": results})


# ==================== AI Research ====================
@main_bp.route("/ai-research")
@login_required
def ai_research():
    """AI Research standalone page"""
    return render_template("ai_research.html")


@main_bp.route("/api/ai-research", methods=["POST"])
@login_required
def api_ai_research():
    """
    AI-powered eBay market research using OpenAI API
    Expects JSON: {item_id: int} or {title: str, condition: str, notes: str}
    """
    from openai import OpenAI

    # Get OpenAI API key from environment
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key:
        return jsonify({
            "ok": False,
            "error": "OpenAI API key not configured. Please add OPENAI_API_KEY to your .env file."
        }), 500

    client = OpenAI(api_key=openai_api_key)

    data = request.get_json() or {}

    # Get item data either from item_id or direct input
    item_id = data.get("item_id")
    if item_id:
        item = Item.query.filter_by(id=item_id, user_id=current_user.id).first()
        if not item:
            return jsonify({"ok": False, "error": "Item not found"}), 404

        item_title = item.title
        condition = item.notes or "Used"
        notes = item.notes or ""
    else:
        item_title = data.get("title", "").strip()
        condition = data.get("condition", "Used")
        notes = data.get("notes", "")

    if not item_title:
        return jsonify({"ok": False, "error": "Item title is required"}), 400

    # Get market settings from user settings or defaults
    settings = get_or_create_settings(current_user.id)
    market_region = data.get("market_region") or "US"
    currency = data.get("currency") or settings.currency or "USD"

    # Build the prompt
    system_prompt = """You are an expert e-commerce pricing analyst specializing in eBay market intelligence.
Your task is to:

1. Search for sold items on eBay in the last 7 days related to the given product title.
2. Clean out irrelevant listings (lots, for parts/not working, accessories only, vague or mismatched titles).
3. Normalize prices including shipping when possible.
4. Summarize findings and provide a competitive pricing recommendation for the user's listing.

Be concise, factual, and analytical.
If too few comparable sales exist, expand the window to the last 14 days and state that clearly."""

    user_prompt = f"""Item title: {item_title}
Condition: {condition}
Relevant notes: {notes}
Market region: {market_region}
Currency: {currency}

Search and Filtering Guidelines:
- Search for "Sold items" on eBay within the last 7 days in {market_region}.
- Focus on identical or equivalent models/variants.
- Exclude:
  - Lots or multi-unit bundles
  - "For parts", "not working", or accessory-only listings
  - Misleading titles or unrelated items
- Adjust for major spec differences (RAM, storage, edition) and note how you normalized the price.
- Compute total buyer price = item price + shipping.
- Distinguish between Auction and Buy It Now formats.
- Remove clear outliers from the range.

Output Format:

1. Brief summary (max 6 lines)
   - Range of sold prices (p25–p75 and full range), median, and valid sample count
   - Key differences influencing price (condition, specs, accessories)
   - Mention any seasonality or trend if relevant (e.g. Q4, collectibles)

2. Competitive pricing recommendation
   - Suggested Buy It Now price
   - Floor (minimum acceptable) price
   - Recommended pricing strategy: BIN vs Auction, shipping policy, coupon suggestion
   - 2–3 short rationale bullets based on comparables and market context

3. JSON structured data
```json
{{
  "query": "{item_title}",
  "window_days": 7,
  "market": "{market_region}",
  "currency": "{currency}",
  "stats": {{
    "count": 0,
    "median": 0,
    "mean": 0,
    "p25": 0,
    "p75": 0,
    "min": 0,
    "max": 0
  }},
  "pricing_recommendation": {{
    "list_price_bin": 0,
    "floor_price": 0,
    "strategy": ["BIN + Best Offer", "Auto-decline below {currency} X", "Free shipping if under 2lb"],
    "rationale": [
      "Median aligned with …",
      "Condition/spec differences …",
      "Active competition …"
    ]
  }},
  "comparables": [
    {{
      "title": "…",
      "sold_price": 0,
      "shipping_price": 0,
      "total_price": 0,
      "date_sold": "YYYY-MM-DD",
      "condition": "…",
      "format": "Auction|BIN",
      "link": "https://…",
      "notes": "Adjustment for specs/condition…"
    }}
  ],
  "exclusions": ["Reasons for excluding outliers or bundles…"],
  "limitations": "If <5 valid comparables, extend to 14 days and/or nearby specs."
}}
```

Output Rules:
- Keep the written summary under 180 words.
- List 3–6 valid comparables with sale dates.
- Clearly state if data is limited or skewed by outliers.

Final instruction:
Return the written summary and recommendation first, followed by the JSON object exactly in the format above."""

    try:
        # Call OpenAI API
        response = client.chat.completions.create(
            model="gpt-4-turbo-preview",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=2000
        )

        result = response.choices[0].message.content

        return jsonify({
            "ok": True,
            "result": result,
            "item_title": item_title
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"OpenAI API error: {str(e)}"
        }), 500
