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
from datetime import datetime

# Dotenv: carga credenciales/vars desde /opt/qventory/qventory/.env
from dotenv import load_dotenv
load_dotenv("/opt/qventory/qventory/.env")

# >>> IMPRESIÓN (lo existente + QR)
import tempfile
import subprocess
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.units import mm
# Importamos el módulo de QR en lugar de barcode
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

    # Conteo total de items del usuario (para el H2)
    total_items = Item.query.filter_by(user_id=current_user.id).count()

    # Filtros de búsqueda
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
        items=items,
        settings=s,
        options=options,
        total_items=total_items,  # <-- para mostrar en el H2: Items ({{ total_items }})
        q=q, fA=fA, fB=fB, fS=fS, fC=fC,
        fPlatform=fPlatform, PLATFORMS=PLATFORMS
    )


# ---------------------- CSV Export/Import (protegido) ----------------------

@main_bp.route("/export/csv")
@login_required
def export_csv():
    """Exporta todos los items del usuario a CSV"""
    items = Item.query.filter_by(user_id=current_user.id).order_by(Item.created_at.asc()).all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Escribir headers
    headers = [
        'id', 'sku', 'title', 'listing_link', 'web_url', 'ebay_url', 
        'amazon_url', 'mercari_url', 'vinted_url', 'poshmark_url', 
        'depop_url', 'A', 'B', 'S', 'C', 'location_code', 'created_at'
    ]
    writer.writerow(headers)
    
    # Escribir datos
    for item in items:
        row = [
            item.id,
            item.sku,
            item.title,
            item.listing_link or '',
            item.web_url or '',
            item.ebay_url or '',
            item.amazon_url or '',
            item.mercari_url or '',
            item.vinted_url or '',
            item.poshmark_url or '',
            item.depop_url or '',
            item.A or '',
            item.B or '',
            item.S or '',
            item.C or '',
            item.location_code or '',
            item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else ''
        ]
        writer.writerow(row)
    
    output.seek(0)
    csv_data = output.getvalue().encode('utf-8')
    output.close()
    
    # Crear nombre de archivo con timestamp
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"qventory_backup_{current_user.username}_{timestamp}.csv"
    
    return send_file(
        io.BytesIO(csv_data),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@main_bp.route("/import/csv", methods=["GET", "POST"])
@login_required
def import_csv():
    """Importa items desde CSV - página de confirmación y procesamiento"""
    if request.method == "GET":
        return render_template("import_csv.html")
    
    # POST: procesar archivo
    if 'csv_file' not in request.files:
        flash("No file selected.", "error")
        return redirect(url_for('main.import_csv'))
    
    file = request.files['csv_file']
    if file.filename == '' or not file.filename.lower().endswith('.csv'):
        flash("Please select a valid CSV file.", "error")
        return redirect(url_for('main.import_csv'))
    
    mode = request.form.get('import_mode', 'add')  # 'add' o 'replace'
    
    try:
        # Leer archivo CSV
        csv_content = file.read().decode('utf-8')
        csv_reader = csv.DictReader(io.StringIO(csv_content))
        
        expected_headers = [
            'id', 'sku', 'title', 'listing_link', 'web_url', 'ebay_url',
            'amazon_url', 'mercari_url', 'vinted_url', 'poshmark_url',
            'depop_url', 'A', 'B', 'S', 'C', 'location_code', 'created_at'
        ]
        
        # Verificar headers
        if not all(header in csv_reader.fieldnames for header in ['sku', 'title']):
            flash("CSV must contain at least 'sku' and 'title' columns.", "error")
            return redirect(url_for('main.import_csv'))
        
        items_to_import = []
        existing_skus = set()
        
        # Si es modo replace, obtener SKUs existentes
        if mode == 'replace':
            existing_items = Item.query.filter_by(user_id=current_user.id).all()
            existing_skus = {item.sku for item in existing_items}
        
        # Procesar filas
        imported_count = 0
        updated_count = 0
        skipped_count = 0
        
        for row_num, row in enumerate(csv_reader, start=2):  # start=2 because header is row 1
            sku = (row.get('sku') or '').strip()
            title = (row.get('title') or '').strip()
            
            if not sku or not title:
                skipped_count += 1
                continue
            
            # Verificar si ya existe el SKU
            existing_item = Item.query.filter_by(user_id=current_user.id, sku=sku).first()
            
            if existing_item and mode == 'add':
                # Modo add: actualizar item existente
                existing_item.title = title
                existing_item.listing_link = (row.get('listing_link') or '').strip() or None
                existing_item.web_url = (row.get('web_url') or '').strip() or None
                existing_item.ebay_url = (row.get('ebay_url') or '').strip() or None
                existing_item.amazon_url = (row.get('amazon_url') or '').strip() or None
                existing_item.mercari_url = (row.get('mercari_url') or '').strip() or None
                existing_item.vinted_url = (row.get('vinted_url') or '').strip() or None
                existing_item.poshmark_url = (row.get('poshmark_url') or '').strip() or None
                existing_item.depop_url = (row.get('depop_url') or '').strip() or None
                existing_item.A = (row.get('A') or '').strip() or None
                existing_item.B = (row.get('B') or '').strip() or None
                existing_item.S = (row.get('S') or '').strip() or None
                existing_item.C = (row.get('C') or '').strip() or None
                existing_item.location_code = (row.get('location_code') or '').strip() or None
                updated_count += 1
            
            elif not existing_item:
                # Crear nuevo item
                new_item = Item(
                    user_id=current_user.id,
                    sku=sku,
                    title=title,
                    listing_link=(row.get('listing_link') or '').strip() or None,
                    web_url=(row.get('web_url') or '').strip() or None,
                    ebay_url=(row.get('ebay_url') or '').strip() or None,
                    amazon_url=(row.get('amazon_url') or '').strip() or None,
                    mercari_url=(row.get('mercari_url') or '').strip() or None,
                    vinted_url=(row.get('vinted_url') or '').strip() or None,
                    poshmark_url=(row.get('poshmark_url') or '').strip() or None,
                    depop_url=(row.get('depop_url') or '').strip() or None,
                    A=(row.get('A') or '').strip() or None,
                    B=(row.get('B') or '').strip() or None,
                    S=(row.get('S') or '').strip() or None,
                    C=(row.get('C') or '').strip() or None,
                    location_code=(row.get('location_code') or '').strip() or None
                )
                db.session.add(new_item)
                imported_count += 1
        
        # Si es modo replace, eliminar items que no están en el CSV
        if mode == 'replace':
            csv_skus = {(row.get('sku') or '').strip() for row in csv.DictReader(io.StringIO(csv_content)) if (row.get('sku') or '').strip()}
            items_to_delete = Item.query.filter_by(user_id=current_user.id).filter(~Item.sku.in_(csv_skus)).all()
            for item in items_to_delete:
                db.session.delete(item)
        
        db.session.commit()
        
        # Mensaje de resultado
        messages = []
        if imported_count > 0:
            messages.append(f"{imported_count} items imported")
        if updated_count > 0:
            messages.append(f"{updated_count} items updated")
        if skipped_count > 0:
            messages.append(f"{skipped_count} rows skipped")
        
        flash(f"Import completed: {', '.join(messages)}.", "ok")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Import failed: {str(e)}", "error")
    
    return redirect(url_for('main.dashboard'))


# ---------------------- eBay Browse API (con .env) ----------------------

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

# Cache simple de token en memoria
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
    r = requests.post(base["oauth"], headers=headers, data=data, timeout=15)
    r.raise_for_status()
    j = r.json()
    _EBAY_TOKEN["value"] = j["access_token"]
    _EBAY_TOKEN["exp"] = now + int(j.get("expires_in", 7200))
    return _EBAY_TOKEN["value"]


# ---------------------- Utilidades URL eBay (solo ID) ----------------------

_EBAY_HOSTS = (
    "ebay.com", "www.ebay.com", "m.ebay.com",
    "ebay.co.uk", "www.ebay.co.uk", "m.ebay.co.uk",
    "ebay.ca", "www.ebay.ca", "m.ebay.ca",
)

def _looks_like_ebay_store_or_search(path: str) -> bool:
    # /str/… (tienda), /sch/… (búsqueda), /b/… (browsing de categoría)
    return bool(re.match(r"^/(?:str|sch|b)/", path, re.I))

def _extract_legacy_id(url: str) -> str | None:
    """
    Extrae el legacy item id desde URLs comunes de eBay.
    Soporta:
      - /itm/123456789012
      - /itm/Titulo/123456789012
      - /itm/123456789012?hash=...
      - parámetros de query: ?item=..., ?iid=..., ?itemid=..., ?itemId=...
      - subdominio móvil m.ebay.*
    """
    try:
        u = urlparse(url)
        path = u.path or ""

        # Si es tienda/búsqueda/categoría, no intentamos
        if _looks_like_ebay_store_or_search(path):
            return None

        # Patrones comunes en el path
        rx_list = [
            r"/itm/(?:[^/]+/)?(\d{9,})",  # /itm/Titulo/123...
            r"/itm/(\d{9,})",            # /itm/123...
            r"/(\d{12})(?:[/?]|$)",      # por si el path termina en el ID
        ]
        for rx in rx_list:
            m = re.search(rx, path)
            if m:
                return m.group(1)

        # Revisa querystring
        qs = parse_qs(u.query)
        for key in ("item", "iid", "itemid", "legacyItemId", "itemId"):
            vals = qs.get(key)
            if vals and len(vals) > 0:
                m = re.search(r"\d{9,}", vals[0])
                if m:
                    return m.group(0)

        # Último recurso: cualquier número largo en toda la URL
        m = re.search(r"(\d{12,})", url)
        return m.group(1) if m else None
    except Exception:
        return None


# ---------------------- API helper: importar título desde URL (SOLO eBay API) ----------------------

@main_bp.route("/api/fetch-market-title")
@login_required
def api_fetch_market_title():
    """
    Recibe ?url=... y devuelve {ok, marketplace, title, fill:{title, ebay_url}}
    Implementación: SOLO eBay Browse API (sin scraping HTML).
    Requiere URL de ítem con legacy_item_id extraíble.
    """
    raw_url = (request.args.get("url") or "").strip()
    if not raw_url:
        return jsonify({"ok": False, "error": "Missing url"}), 400
    if not re.match(r"^https?://", raw_url, re.I):
        return jsonify({"ok": False, "error": "Invalid URL"}), 400

    u = urlparse(raw_url)
    host = (u.netloc or "").lower()
    path = u.path or ""

    # Verificación temprana: si es eBay pero NO es /itm/... (o similar), error claro
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
            return jsonify({
                "ok": False,
                "error": "404: legacy_item_id no encontrado por Browse API en este entorno."
            }), 404

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
        return jsonify({"ok": False, "error": f"HTTP {code}: {body}"}), 502
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 502


# ---------------------- CRUD Items (protegido) ----------------------

@main_bp.route("/item/new", methods=["GET", "POST"])
@login_required
def new_item():
    s = get_or_create_settings(current_user)

    if request.method == "POST":
        # Campos base
        title = (request.form.get("title") or "").strip()
        listing_link = (request.form.get("listing_link") or "").strip() or None

        web_url     = (request.form.get("web_url") or "").strip() or None
        ebay_url    = (request.form.get("ebay_url") or "").strip() or None
        amazon_url  = (request.form.get("amazon_url") or "").strip() or None
        mercari_url = (request.form.get("mercari_url") or "").strip() or None
        vinted_url  = (request.form.get("vinted_url") or "").strip() or None
        poshmark_url= (request.form.get("poshmark_url") or "").strip() or None
        depop_url   = (request.form.get("depop_url") or "").strip() or None

        # Location levels
        A  = (request.form.get("A") or "").strip() or None
        B  = (request.form.get("B") or "").strip() or None
        S_ = (request.form.get("S") or "").strip() or None
        C  = (request.form.get("C") or "").strip() or None

        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("main.new_item"))

        # Crear item
        sku = generate_sku()
        loc = compose_location_code(A=A, B=B, S=S_, C=C, enabled=tuple(s.enabled_levels()))
        it = Item(
            user_id=current_user.id,
            title=title,
            sku=sku,
            listing_link=listing_link,
            web_url=web_url,
            ebay_url=ebay_url,
            amazon_url=amazon_url,
            mercari_url=mercari_url,
            vinted_url=vinted_url,
            poshmark_url=poshmark_url,
            depop_url=depop_url,
            A=A, B=B, S=S_, C=C,
            location_code=loc
        )
        db.session.add(it)
        db.session.commit()

        action = (request.form.get("submit_action") or "create").strip()

        if action == "create_another":
            # Guardar y quedarse en la misma página con el formulario limpio
            flash("Item created. You can add another.", "ok")
            return render_template("new_item.html", settings=s, item=None)

        # Flujo normal: redirigir (dashboard o detalle)
        flash("Item created.", "ok")
        return redirect(url_for("main.dashboard"))

    # GET
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

    # Construye links públicos usando el username del dueño
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
    # Pasamos username para usarlo en los enlaces de QR dentro de la plantilla
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
    # Evita caché agresiva: así se actualiza bien en clientes
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "application/javascript"
    return resp


@main_bp.route("/offline")
def offline():
    # No requiere login; es fallback de PWA
    return render_template("offline.html")


# ====================== helpers + ruta de IMPRESIÓN con QR ======================

def _ellipsize(s: str, n: int = 20) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[:n].rstrip() + "…"

def _build_item_label_pdf(it, settings) -> bytes:
    """
    PDF 40x30 mm con:
      - QR code del SKU centrado
      - Título (20 chars + …) centrado
      - Ubicación centrada
    Todo el bloque queda centrado verticalmente en el sticker.
    """
    W = 40 * mm
    H = 30 * mm

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(W, H))

    # Márgenes
    m = 3 * mm
    inner_w = W - 2 * m
    inner_h = H - 2 * m

    # Fuentes / métricas
    title_fs = 8
    loc_fs = 8
    leading = 1.2  # factor de línea para estimar altura de texto
    title_h = title_fs * leading
    loc_h = loc_fs * leading

    # Separaciones entre elementos
    gap_qr_title = 1.5 * mm
    gap_title_loc = 0.8 * mm

    # Tamaño del QR code (cuadrado)
    qr_size = 15 * mm  # Tamaño del QR en el PDF
    
    # Altura total del bloque para centrarlo verticalmente
    block_h = qr_size + gap_qr_title + title_h + gap_title_loc + loc_h
    y0 = m + (inner_h - block_h) / 2.0  # base del bloque

    # --- QR CODE ---
    sku = it.sku or ""
    
    # Generar QR code con el SKU
    qr = qrcode.QRCode(
        version=1,  # Tamaño automático
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=1,
    )
    qr.add_data(sku)
    qr.make(fit=True)
    
    # Crear imagen del QR (PIL Image)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Convertir a RGB si es necesario (qrcode puede devolver modo '1' o 'L')
    if qr_img.mode != 'RGB':
        qr_img = qr_img.convert('RGB')
    
    # Calcular posición centrada del QR
    x_qr = m + (inner_w - qr_size) / 2.0
    
    # Dibujar QR code directamente desde PIL Image
    c.drawImage(qr_img, x_qr, y0, width=qr_size, height=qr_size, preserveAspectRatio=True)

    # --- TÍTULO ---
    title = _ellipsize(it.title or "", 20)
    c.setFont("Helvetica-Bold", title_fs)
    y_title = y0 + qr_size + gap_qr_title + title_fs
    c.drawCentredString(W / 2.0, y_title, title)

    # --- UBICACIÓN ---
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

    printer_name = os.environ.get("QVENTORY_PRINTER")  # opcional, desde .env
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
        # No existe 'lp' (CUPS) en el sistema: ofrece descarga
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