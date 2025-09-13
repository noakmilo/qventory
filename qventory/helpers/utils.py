import datetime, random, string, io
from PIL import Image, ImageDraw, ImageFont
import qrcode
from flask import current_app
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader

from ..extensions import db
from ..models.setting import Setting
from ..models.item import Item
from ..models.user import User

def get_or_create_settings(user):
    uid = user.id if hasattr(user, "id") else int(user)
    s = Setting.query.filter_by(user_id=uid).first()
    if not s:
        s = Setting(user_id=uid)
        db.session.add(s)
        db.session.commit()
    return s

def generate_sku():
    today = datetime.datetime.utcnow().strftime("%Y%m%d")
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    sku = f"INV-{today}-{suffix}"
    while Item.query.filter_by(sku=sku).first() is not None:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        sku = f"INV-{today}-{suffix}"
    return sku

def compose_location_code(A=None, B=None, S=None, C=None, enabled=("A","B","S","C")):
    parts = []
    if "A" in enabled and A: parts.append(f"A{A}")
    if "B" in enabled and B: parts.append(f"B{B}")
    if "S" in enabled and S: parts.append(f"S{S}")
    if "C" in enabled and C: parts.append(f"C{C}")
    return "".join(parts)

def parse_location_code(code):
    result = {}
    if not code: return result
    i = 0
    current_key = None
    current_val = []
    while i < len(code):
        ch = code[i]
        if ch in "ABSC":
            if current_key:
                result[current_key] = "".join(current_val).strip() or None
                current_val = []
            current_key = ch
        else:
            current_val.append(ch)
        i += 1
    if current_key:
        result[current_key] = "".join(current_val).strip() or None
    return result

# Batch helpers
def parse_values(expr):
    if not expr:
        return []
    expr = expr.strip()
    if "-" in expr and "," not in expr:
        try:
            a,b = expr.split("-",1)
            a,b = int(a.strip()), int(b.strip())
            if a <= b:
                return [str(i) for i in range(a,b+1)]
            else:
                return [str(i) for i in range(b,a+1)]
        except Exception:
            pass
    return [v.strip() for v in expr.split(",") if v.strip()]

def human_from_code(code, settings):
    parts = parse_location_code(code)
    labels = settings.labels_map()
    segs = []
    if settings.enable_A and parts.get("A"):
        segs.append(f"{labels['A']} {parts['A']}")
    if settings.enable_B and parts.get("B"):
        segs.append(f"{labels['B']} {parts['B']}")
    if settings.enable_S and parts.get("S"):
        segs.append(f"{labels['S']} {parts['S']}")
    if settings.enable_C and parts.get("C"):
        segs.append(f"{labels['C']} {parts['C']}")
    return " • ".join(segs) if segs else "Location"

def qr_label_image(code, human_text, link, qr_px=300):
    qr_img = qrcode.make(link).convert("RGB").resize((qr_px, qr_px), Image.NEAREST)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 40)
    except Exception:
        font = ImageFont.load_default()

    pad = 24
    gap = 12
    tmp = Image.new("RGB", (10,10), "white")
    d0 = ImageDraw.Draw(tmp)
    hw, hh = d0.textbbox((0,0), human_text, font=font)[2:]
    cw, ch = d0.textbbox((0,0), code, font=font)[2:]

    width = max(qr_img.width, hw, cw) + pad*2
    height = pad + qr_img.height + gap + hh + 4 + ch + pad
    out = Image.new("RGB", (width, height), "white")
    d = ImageDraw.Draw(out)
    x_qr = (width - qr_img.width)//2
    out.paste(qr_img, (x_qr, pad))
    y_text = pad + qr_img.height + gap
    d.text(((width-hw)//2, y_text), human_text, fill=(0,0,0), font=font)
    y_code = y_text + hh + 4
    d.text(((width-cw)//2, y_code), code, fill=(0,0,0), font=font)
    return out

# PDF batch utility
def build_qr_batch_pdf(codes, settings, make_link):
    page_w, page_h = letter
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)

    cols, rows, qr_px = 2, 5, 300  # defaults; caller can change if desired
    margin = 36
    grid_w = page_w - margin*2
    grid_h = page_h - margin*2
    cell_w = grid_w / cols
    cell_h = grid_h / rows

    for i, code in enumerate(codes):
        link = make_link(code)
        human = human_from_code(code, settings)
        img = qr_label_image(code, human, link, qr_px=qr_px)

        row = (i // cols) % rows
        col = i % cols
        x = margin + col * cell_w
        y = page_h - margin - (row+1) * cell_h

        pad = 6
        max_w = cell_w - pad*2
        max_h = cell_h - pad*2
        iw, ih = img.size
        scale = min(max_w/iw, max_h/ih, 1.0)
        draw_w = iw * scale
        draw_h = ih * scale

        dx = x + (cell_w - draw_w)/2
        dy = y + (cell_h - draw_h)/2

        c.drawImage(ImageReader(img), dx, dy, width=draw_w, height=draw_h)

        if (i+1) % (cols*rows) == 0 and (i+1) < len(codes):
            c.showPage()

    c.save()
    buf.seek(0)
    return buf
