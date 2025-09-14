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

# =========================
#   Utilidades de sistema
# =========================

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
    sku = f"{today}-{suffix}"
    while Item.query.filter_by(sku=sku).first() is not None:
        suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
        sku = f"{today}-{suffix}"
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

# =========================
#   Batch helpers
# =========================

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
    if getattr(settings, "enable_A", False) and parts.get("A"):
        segs.append(f"{labels['A']} {parts['A']}")
    if getattr(settings, "enable_B", False) and parts.get("B"):
        segs.append(f"{labels['B']} {parts['B']}")
    if getattr(settings, "enable_S", False) and parts.get("S"):
        segs.append(f"{labels['S']} {parts['S']}")
    if getattr(settings, "enable_C", False) and parts.get("C"):
        segs.append(f"{labels['C']} {parts['C']}")
    return " • ".join(segs) if segs else "Location"

# =========================
#   Render QR (PIL) - fila horizontal
# =========================

def qr_label_image(code, human_text, link, qr_px=220, *, min_qr_px=140):
    """
    Genera una imagen PIL con layout horizontal:
      [ QR ]  [ B1S2C1 ]
    - Solo dibuja 'code' (p.ej. B1S2C1), NO el human_text.
    - QR y texto quedan en la MISMA FILA, centrados verticalmente.
    """
    pad = 20
    gap = 16
    pref_font_px = 48
    min_font_px  = 22

    def _load_font(size):
        try:
            return ImageFont.truetype("DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()

    # QR inicial
    qr_side = max(min_qr_px, int(qr_px))
    qr_img = qrcode.make(link).convert("RGB").resize((qr_side, qr_side), Image.NEAREST)

    # Texto
    font_size = pref_font_px
    font = _load_font(font_size)

    def measure_text(txt, fnt):
        tmp = Image.new("RGB", (10, 10), "white")
        d0 = ImageDraw.Draw(tmp)
        l, t, r, b = d0.textbbox((0, 0), txt, font=fnt)
        return (r - l), (b - t)

    text_w, text_h = measure_text(code or "", font)
    out_h = qr_side + pad*2

    # Reducir fuente si el texto es más alto que QR
    while (text_h > qr_side) and (font_size > min_font_px):
        font_size -= 1
        font = _load_font(font_size)
        text_w, text_h = measure_text(code or "", font)

    # Reducir QR si aún no cabe
    while (text_h > qr_side) and (qr_side > min_qr_px):
        qr_side -= 2
        qr_img = qrcode.make(link).convert("RGB").resize((qr_side, qr_side), Image.NEAREST)
        out_h = qr_side + pad*2

    # Calcular ancho total
    out_w = pad + qr_side + gap + max(1, text_w) + pad

    out = Image.new("RGB", (out_w, out_h), "white")
    d = ImageDraw.Draw(out)

    # Pegar QR
    qr_x = pad
    qr_y = pad
    out.paste(qr_img, (qr_x, qr_y))

    # Texto centrado verticalmente
    text_x = qr_x + qr_side + gap
    text_y = pad + (qr_side - text_h) // 2
    d.text((text_x, text_y), code or "", fill=(0, 0, 0), font=font)

    return out

# =========================
#   PDF 40x30 mm: QR izq + SOLO código a la derecha
# =========================

def mm_to_pt(mm: float) -> float:
    return mm * 72.0 / 25.4

def _make_qr_pil(link: str, target_pt: float, dpi: int = 300):
    px = max(16, int(round(target_pt * dpi / 72.0)))
    img = qrcode.make(link).convert("RGB").resize((px, px), Image.NEAREST)
    return img

def build_qr_batch_pdf(codes, settings, make_link):
    page_w, page_h = letter
    margin = 18

    LABEL_W_PT = mm_to_pt(40.0)
    LABEL_H_PT = mm_to_pt(30.0)

    PAD = 4
    TEXT_FONT = "Helvetica"
    PREF_TEXT_SIZE = 12
    MIN_TEXT_SIZE = 9
    DPI = 300

    QR_MAX_PT = max(1.0, LABEL_H_PT - 2 * PAD)
    QR_MIN_PT = mm_to_pt(16.0)

    cols = max(1, int((page_w - 2*margin) // LABEL_W_PT))
    rows = max(1, int((page_h - 2*margin) // LABEL_H_PT))
    grid_w = cols * LABEL_W_PT
    grid_h = rows * LABEL_H_PT
    left = (page_w - grid_w) / 2.0
    bottom = (page_h - grid_h) / 2.0

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setAuthor("Qventory")
    c.setTitle("QR Labels 40x30mm")

    def _truncate_to_width(text: str, max_width_pt: float, font_size: int) -> str:
        if not text:
            return ""
        if c.stringWidth(text, TEXT_FONT, font_size) <= max_width_pt:
            return text
        ell = "…"
        ell_w = c.stringWidth(ell, TEXT_FONT, font_size)
        acc = ""
        for ch in text:
            if c.stringWidth(acc + ch, TEXT_FONT, font_size) + ell_w > max_width_pt:
                break
            acc += ch
        return acc + ell

    for i, code in enumerate(codes):
        if i > 0 and i % (cols * rows) == 0:
            c.showPage()

        idx = i % (cols * rows)
        row = rows - 1 - (idx // cols)
        col = idx % cols

        x0 = left + col * LABEL_W_PT
        y0 = bottom + row * LABEL_H_PT

        link = make_link(code)
        text_value = code or ""

        chosen_font = PREF_TEXT_SIZE
        qr_side_pt = QR_MAX_PT

        def text_area_width(qr_pt: float):
            return max(1.0, LABEL_W_PT - (qr_pt + 3 * PAD))

        def text_width(font_size: int):
            return c.stringWidth(text_value, TEXT_FONT, font_size)

        tw = text_area_width(qr_side_pt)
        required = text_width(chosen_font)

        if required > tw:
            qr_allowed = LABEL_W_PT - (required + 3 * PAD)
            qr_side_pt = max(QR_MIN_PT, min(QR_MAX_PT, qr_allowed))
            tw = text_area_width(qr_side_pt)

        if required > tw:
            for size in (11, 10, 9):
                required = text_width(size)
                qr_allowed = LABEL_W_PT - (required + 3 * PAD)
                if qr_allowed >= QR_MIN_PT:
                    chosen_font = size
                    qr_side_pt = min(QR_MAX_PT, qr_allowed)
                    tw = text_area_width(qr_side_pt)
                    break
                else:
                    chosen_font = size
                    qr_side_pt = QR_MIN_PT
                    tw = text_area_width(qr_side_pt)
                    if required <= tw:
                        break

        c.setFont(TEXT_FONT, chosen_font)
        line = _truncate_to_width(text_value, tw, chosen_font)

        qr_img = _make_qr_pil(link, qr_side_pt, dpi=DPI)
        qr_y = y0 + (LABEL_H_PT - qr_side_pt) / 2.0
        c.drawImage(
            ImageReader(qr_img),
            x0 + PAD,
            qr_y,
            width=qr_side_pt,
            height=qr_side_pt,
            preserveAspectRatio=True,
            mask='auto'
        )

        text_x = x0 + PAD + qr_side_pt + PAD
        text_y = y0 + (LABEL_H_PT - chosen_font) / 2.0
        c.drawString(text_x, text_y, line)

    c.save()
    buf.seek(0)
    return buf
