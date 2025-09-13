from flask import render_template, request, redirect, url_for, send_file, flash, Response
from flask_login import login_required, current_user
from sqlalchemy import or_

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
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


# ---------------------- SEO extra (opcional) ----------------------

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
