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
#   Render QR (PIL)
# =========================

def qr_label_image(code, human_text, link, qr_px=300):
    """
    (Mantener por compatibilidad) Devuelve una imagen de etiqueta apilada verticalmente.
    NOTA: Para el layout 40x30 mm con QR a la izquierda y texto a la derecha,
    ahora usamos la composición directa en PDF (ver build_qr_batch_pdf).
    """
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

# =========================
#   PDF: 40x30 mm, QR izq, texto der 12 pt
# =========================

def mm_to_pt(mm: float) -> float:
    """Convierte milímetros a puntos (1 in = 25.4 mm; 1 in = 72 pt)."""
    return mm * 72.0 / 25.4

def _make_qr_pil(link: str, target_pt: float, dpi: int = 300):
    """
    Genera una imagen PIL cuadrada del QR a un tamaño físico 'target_pt' (en puntos PDF),
    rasterizada a 'dpi' para que imprima nítido.
    """
    px = int(round(target_pt * dpi / 72.0))
    img = qrcode.make(link).convert("RGB").resize((px, px), Image.NEAREST)
    return img

def build_qr_batch_pdf(codes, settings, make_link):
    """
    Construye un PDF con etiquetas de 40x30 mm:
      - QR a la izquierda (alto completo menos padding).
      - Texto a la derecha (human_text + code) en 12 pt.
    Se auto-calcula cuántas etiquetas caben por página carta con el margen dado.
    """
    # Página
    page_w, page_h = letter
    margin = 18  # ~6 mm de margen exterior; ajusta a gusto

    # Etiqueta 40 x 30 mm
    LABEL_W_PT = mm_to_pt(40.0)
    LABEL_H_PT = mm_to_pt(30.0)

    # Layout interno
    PAD = 4                 # padding interno en pt
    TEXT_FONT = "Helvetica" # tipografía estándar PDF
    TEXT_SIZE = 12          # tamaño requerido
    LINE_GAP = 2            # separación entre líneas
    DPI = 300               # usa 203 si tu impresora es 203 dpi

    # Grilla: cuántas etiquetas caben
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

    # Función local para truncar texto al ancho
    def _truncate_to_width(text: str, max_width_pt: float) -> str:
        if not text:
            return ""
        if c.stringWidth(text, TEXT_FONT, TEXT_SIZE) <= max_width_pt:
            return text
        ell = "…"
        ell_w = c.stringWidth(ell, TEXT_FONT, TEXT_SIZE)
        acc = ""
        for ch in text:
            if c.stringWidth(acc + ch, TEXT_FONT, TEXT_SIZE) + ell_w > max_width_pt:
                break
            acc += ch
        return acc + ell

    for i, code in enumerate(codes):
        # Nueva página si se llenó la grilla completa
        if i > 0 and i % (cols * rows) == 0:
            c.showPage()

        idx = i % (cols * rows)
        row = rows - 1 - (idx // cols)  # contamos de arriba hacia abajo
        col = idx % cols

        # Origen (esquina inferior izquierda) de la etiqueta actual
        x0 = left + col * LABEL_W_PT
        y0 = bottom + row * LABEL_H_PT

        # Datos de la etiqueta
        link = make_link(code)
        human = human_from_code(code, settings)

        # QR: lado = altura de la etiqueta - 2*PAD
        qr_side_pt = max(1.0, LABEL_H_PT - 2 * PAD)
        qr_img = _make_qr_pil(link, qr_side_pt, dpi=DPI)

        # Dibuja QR
        c.drawImage(
            ImageReader(qr_img),
            x0 + PAD,
            y0 + PAD,
            width=qr_side_pt,
            height=qr_side_pt,
            preserveAspectRatio=True,
            mask='auto'
        )

        # Área de texto a la derecha del QR
        text_x = x0 + PAD + qr_side_pt + PAD
        text_w = max(1.0, LABEL_W_PT - (qr_side_pt + 3 * PAD))
        text_top = y0 + LABEL_H_PT - PAD

        c.setFont(TEXT_FONT, TEXT_SIZE)

        # Dos líneas: human_text y code
        line1 = _truncate_to_width(human or "Location", text_w)
        line2 = _truncate_to_width(code or "", text_w)

        # Posición de líneas (desde arriba hacia abajo)
        y_line1 = text_top - TEXT_SIZE
        y_line2 = y_line1 - (TEXT_SIZE + LINE_GAP)

        c.drawString(text_x, y_line1, line1)
        c.drawString(text_x, y_line2, line2)

        # (opcional) guía de corte / borde de la etiqueta:
        # c.setLineWidth(0.25)
        # c.rect(x0, y0, LABEL_W_PT, LABEL_H_PT)

    c.save()
    buf.seek(0)
    return buf
