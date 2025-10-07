import datetime, random, string, io
from PIL import Image, ImageDraw, ImageFont
import qrcode
from qrcode.constants import ERROR_CORRECT_L
from flask import current_app
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.lib.units import mm

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

def is_valid_location_code(sku):
    """
    Check if a SKU string matches Qventory location code format
    Valid formats: A1, B2S3, A1B2, A1B2S3C4, S3C1, C5, etc.

    Args:
        sku: SKU string to validate

    Returns:
        bool: True if valid location code format
    """
    if not sku:
        return False

    # Must start with A, B, S, or C
    if not sku or sku[0] not in 'ABSC':
        return False

    # Parse the code
    parts = parse_location_code(sku)

    # Must have at least one component
    if not parts:
        return False

    # All components must have numeric values
    import re
    for key, value in parts.items():
        if not value or not re.match(r'^\d+$', value):
            return False

    # Keys must be valid and in order (A before B before S before C)
    valid_keys = ['A', 'B', 'S', 'C']
    keys_present = [k for k in valid_keys if k in parts]

    # Check if keys maintain order
    last_index = -1
    for key in parts.keys():
        if key not in valid_keys:
            return False
        current_index = valid_keys.index(key)
        if current_index <= last_index:
            return False
        last_index = current_index

    return True

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
#   Helpers unidades
# =========================

def mm_to_pt(mm_val: float) -> float:
    return mm_val * 72.0 / 25.4

# =========================
#   QR nítido (PIL)
# =========================

def _make_qr_pil(link: str, target_side_pt: float, dpi: int = 300, *, border: int = 2):
    """
    Crea un QR cuadrado de ~target_side_pt (en puntos) a 'dpi', con
    bordes pequeños y corrección L para mayor nitidez.
    """
    target_px = max(64, int(round(target_side_pt * dpi / 72.0)))
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_L,
        box_size=10,
        border=border,
    )
    qr.add_data(link or "")
    qr.make(fit=True)
    base = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = base.resize((target_px, target_px), Image.NEAREST)
    return img

# =========================
#   Etiqueta individual QR (PIL) 40x30mm
# =========================

def qr_label_image(code, human_text, link, qr_px=None, *, dpi=300):
    """
    Devuelve una imagen PIL de 40x30 mm a 'dpi' con:
      - QR centrado arriba
      - "Location: CODE" centrado debajo (Helvetica-Bold 8pt)
    Param:
      qr_px: tamaño máximo deseado del QR en píxeles (opcional). Si no se da,
              se calcula automáticamente según la etiqueta.
    """
    # --- Tamaño etiqueta 40x30mm en píxeles ---
    LABEL_W_MM, LABEL_H_MM = 40.0, 30.0
    W_px = int(round(mm_to_pt(LABEL_W_MM) * dpi / 72.0))
    H_px = int(round(mm_to_pt(LABEL_H_MM) * dpi / 72.0))

    # Márgenes/gaps
    PAD_Y_px = int(round(mm_to_pt(3) * dpi / 72.0))     # ≈3 mm
    GAP_px   = int(round(mm_to_pt(1.5) * dpi / 72.0))   # ≈1.5 mm
    MIN_QR_PX = 64

    # Fuente 8pt bold
    def _load_bold(size_px):
        try:
            return ImageFont.truetype("Helvetica-Bold.ttf", size_px)
        except Exception:
            try:
                return ImageFont.truetype("DejaVuSans-Bold.ttf", size_px)
            except Exception:
                return ImageFont.load_default()

    font_px = max(16, int(round(12 * dpi / 72.0)))  # 8pt → px
    font = _load_bold(font_px)
    text = f"Location: {code or ''}"

    # Medición de texto
    tmp = Image.new("RGB", (10, 10), "white")
    d0 = ImageDraw.Draw(tmp)
    l, t, r, b = d0.textbbox((0, 0), text, font=font)
    text_w, text_h = r - l, b - t

    # Alto disponible para QR (arriba)
    available_qr_h = H_px - 2 * PAD_Y_px - GAP_px - text_h
    available_qr_w = W_px - 2 * PAD_Y_px
    auto_qr_side = max(MIN_QR_PX, min(available_qr_h, available_qr_w))

    # Si viene qr_px desde la ruta, úsalo como tope superior (sin romper layout)
    if isinstance(qr_px, (int, float)) and qr_px > 0:
        qr_side_px = int(min(qr_px, auto_qr_side))
        qr_side_px = max(MIN_QR_PX, qr_side_px)
    else:
        qr_side_px = auto_qr_side

    # Generar QR nítido
    qr_img = _make_qr_pil(link, target_side_pt=qr_side_px * 72.0 / dpi, dpi=dpi, border=2)

    # Lienzo
    out = Image.new("RGB", (W_px, H_px), "white")
    d = ImageDraw.Draw(out)

    # Posiciones centradas
    qr_x = (W_px - qr_side_px) // 2
    qr_y = PAD_Y_px  # bloque superior
    out.paste(qr_img.resize((qr_side_px, qr_side_px), Image.NEAREST), (qr_x, qr_y))

    text_x = (W_px - text_w) // 2
    text_y = qr_y + qr_side_px + GAP_px
    d.text((text_x, text_y), text, fill=(0, 0, 0), font=font)

    return out


# =========================
#   PDF batch 40x30mm
# =========================

def build_qr_batch_pdf(codes, settings, make_link, *, dpi=300):
    page_w, page_h = letter
    margin = 18

    LABEL_W_PT = mm_to_pt(40.0)
    LABEL_H_PT = mm_to_pt(30.0)

    GAP    = mm_to_pt(1.5)
    TEXT_FONT = "Helvetica-Bold"
    TEXT_SIZE = 8

    cols = max(1, int((page_w - 2 * margin) // LABEL_W_PT))
    rows = max(1, int((page_h - 2 * margin) // LABEL_H_PT))
    grid_w = cols * LABEL_W_PT
    grid_h = rows * LABEL_H_PT
    left = (page_w - grid_w) / 2.0
    bottom = (page_h - grid_h) / 2.0

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=letter)
    c.setAuthor("Qventory")
    c.setTitle("QR Labels 40x30mm")

    for i, code in enumerate(codes):
        if i > 0 and i % (cols * rows) == 0:
            c.showPage()

        idx = i % (cols * rows)
        row = rows - 1 - (idx // cols)
        col = idx % cols

        x0 = left + col * LABEL_W_PT
        y0 = bottom + row * LABEL_H_PT

        text_val = f"Location: {code or ''}"
        c.setFont(TEXT_FONT, TEXT_SIZE)
        text_w = c.stringWidth(text_val, TEXT_FONT, TEXT_SIZE)
        text_h = TEXT_SIZE

        inner_w = LABEL_W_PT
        inner_h = LABEL_H_PT

        qr_max_side = min(inner_w, inner_h - GAP - text_h)
        qr_max_side = max(mm_to_pt(16.0), qr_max_side)

        link = make_link(code)
        qr_img = _make_qr_pil(link, target_side_pt=qr_max_side, dpi=dpi, border=2)

        block_h = qr_max_side + GAP + text_h
        block_y0 = y0 + (LABEL_H_PT - block_h) / 2.0

        c.drawImage(
            ImageReader(qr_img),
            x0 + (LABEL_W_PT - qr_max_side) / 2.0,
            block_y0 + text_h + GAP,
            width=qr_max_side,
            height=qr_max_side,
            preserveAspectRatio=True,
            mask='auto'
        )

        c.setFont(TEXT_FONT, TEXT_SIZE)
        c.drawCentredString(x0 + LABEL_W_PT / 2.0, block_y0, text_val)

    c.save()
    buf.seek(0)
    return buf
