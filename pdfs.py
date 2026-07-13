"""PDF generation with reportlab (handoff §8). Phase 2: bib stickers + bib lists.

Later phases add heat sheets / meet-day packets (track).
"""
import io

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

# Avery label geometry (US Letter), in inches: (cols, rows, label_w, label_h,
# top_margin, side_margin, pitch_x, pitch_y).
TEMPLATES = {
    "5160": dict(cols=3, rows=10, lw=2.625, lh=1.0, top=0.5, side=0.1875,
                 px=2.75, py=1.0),
    "5163": dict(cols=2, rows=5, lw=4.0, lh=2.0, top=0.5, side=0.15625,
                 px=4.1875, py=2.0),
}


def _qr_image(text):
    import qrcode
    img = qrcode.make(text)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return ImageReader(buf)


def bib_stickers_pdf(school_name, athletes, *, template="5160", qr_prefix=""):
    """Sheet of Avery labels: bib + name + QR (+ school). `athletes` are dict-likes
    with keys bib, name. `qr_prefix` lets you encode a URL like '.../bibcheck?bib='."""
    t = TEMPLATES.get(template, TEMPLATES["5160"])
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    per_page = t["cols"] * t["rows"]

    items = [a for a in athletes if a["bib"] is not None]
    for i, a in enumerate(items):
        slot = i % per_page
        if i and slot == 0:
            c.showPage()
        col = slot % t["cols"]
        row = slot // t["cols"]
        x = t["side"] * inch + col * t["px"] * inch
        y_top = ph - t["top"] * inch - row * t["py"] * inch
        lw, lh = t["lw"] * inch, t["lh"] * inch
        pad = 0.08 * inch

        # QR on the right
        qr_sz = min(lh - 2 * pad, 0.8 * inch)
        qr_text = f"{qr_prefix}{a['bib']}" if qr_prefix else str(a["bib"])
        try:
            c.drawImage(_qr_image(qr_text), x + lw - qr_sz - pad,
                        y_top - qr_sz - pad, qr_sz, qr_sz,
                        preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001 — never let one bad label kill the sheet
            pass

        # Bib number (large) + name + school on the left
        c.setFont("Helvetica-Bold", 20)
        c.drawString(x + pad, y_top - 0.34 * inch, f"#{a['bib']}")
        c.setFont("Helvetica", 10)
        c.drawString(x + pad, y_top - 0.54 * inch, (a["name"] or "")[:26])
        c.setFont("Helvetica", 7)
        c.setFillGray(0.4)
        c.drawString(x + pad, y_top - 0.70 * inch, (school_name or "")[:32])
        c.setFillGray(0)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def bib_list_pdf(school_name, athletes):
    """Simple printable roster: bib, name, grade, gender."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    left = 0.75 * inch
    y = ph - 0.9 * inch

    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, f"{school_name} — Roster")
    y -= 0.35 * inch
    c.setFont("Helvetica-Bold", 10)
    c.setFillGray(0.35)
    for label, dx in (("BIB", 0), ("NAME", 0.9 * inch), ("GR", 3.6 * inch),
                      ("SEX", 4.2 * inch)):
        c.drawString(left + dx, y, label)
    c.setFillGray(0)
    y -= 0.06 * inch
    c.line(left, y, pw - 0.75 * inch, y)
    y -= 0.22 * inch

    c.setFont("Helvetica", 11)
    for a in athletes:
        if y < 0.9 * inch:
            c.showPage()
            y = ph - 0.9 * inch
            c.setFont("Helvetica", 11)
        c.drawString(left, y, "" if a["bib"] is None else str(a["bib"]))
        c.drawString(left + 0.9 * inch, y, (a["name"] or "")[:40])
        c.drawString(left + 3.6 * inch, y, "" if a["grade"] is None else str(a["grade"]))
        c.drawString(left + 4.2 * inch, y, a["gender"] or "")
        y -= 0.26 * inch

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
