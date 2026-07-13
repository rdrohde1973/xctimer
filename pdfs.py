"""PDF generation with reportlab (handoff §8). Phase 2: bib stickers + bib lists.

Later phases add heat sheets / meet-day packets (track).
"""
import io
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as pdfcanvas

NAVY = (0.086, 0.259, 0.443)  # brand navy #164271


def _logo_reader(logo_path):
    """Resolve a '/static/...' logo URL to an ImageReader, or None."""
    if not logo_path:
        return None
    p = os.path.join(os.path.dirname(__file__), logo_path.lstrip("/"))
    if os.path.exists(p):
        try:
            return ImageReader(p)
        except Exception:  # noqa: BLE001
            return None
    return None

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


def bib_stickers_pdf(school_name, athletes, *, template="5160", qr_prefix="", logo_path=None):
    """Avery label sheet for one school: logo + bib + name + school + QR."""
    t = TEMPLATES.get(template, TEMPLATES["5160"])
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    _pw, ph = letter
    per_page = t["cols"] * t["rows"]
    logo = _logo_reader(logo_path)
    items = [a for a in athletes if a["bib"] is not None]
    for i, a in enumerate(items):
        slot = i % per_page
        if i and slot == 0:
            c.showPage()
        _draw_label(c, t, slot, ph, a, school_name, qr_prefix, logo)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def _draw_heat_section(c, ph, pw, left, title, rows, laned):
    """Draw one event's heats (one heat/section per page) onto canvas `c`."""
    from collections import OrderedDict
    groups = OrderedDict()
    for r in rows:
        groups.setdefault(r["heat"] or 1, []).append(r)
    if not groups:
        groups[1] = []
    unit = "Heat" if laned else "Section"
    for heat, items in groups.items():
        y = ph - 0.9 * inch
        c.setFont("Helvetica-Bold", 16)
        c.drawString(left, y, title[:70])
        y -= 0.3 * inch
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left, y, f"{unit} {heat}")
        y -= 0.32 * inch
        c.setFont("Helvetica-Bold", 9)
        c.setFillGray(0.35)
        cols = ([("LANE", 0)] if laned else [("", 0)]) + \
               [("BIB", 0.7 * inch), ("NAME", 1.4 * inch), ("SCHOOL", 3.7 * inch),
                ("MARK / TIME", 5.6 * inch)]
        for label, dx in cols:
            c.drawString(left + dx, y, label)
        c.setFillGray(0)
        y -= 0.06 * inch
        c.line(left, y, pw - 0.6 * inch, y)
        y -= 0.26 * inch
        c.setFont("Helvetica", 11)
        items = sorted(items, key=lambda r: (r["lane"] or 0))
        for r in items:
            if y < 0.9 * inch:
                c.showPage()
                y = ph - 0.9 * inch
                c.setFont("Helvetica", 11)
            if laned:
                c.drawString(left, y, str(r["lane"] or ""))
            c.drawString(left + 0.7 * inch, y, "" if r["bib"] is None else str(r["bib"]))
            c.drawString(left + 1.4 * inch, y, (r["name"] or "")[:26])
            c.drawString(left + 3.7 * inch, y, (r["school"] or "")[:22])
            c.line(left + 5.6 * inch, y - 0.02 * inch, pw - 0.6 * inch, y - 0.02 * inch)
            y -= 0.34 * inch
        c.showPage()


def heat_sheet_pdf(title, rows, *, laned=True):
    """Meet-day packet for one event: entries grouped by heat/section, blank mark column."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    _draw_heat_section(c, ph, pw, 0.75 * inch, title, rows, laned)
    c.save()
    buf.seek(0)
    return buf.read()


def multi_heat_sheet_pdf(sections):
    """Meet-wide heat sheets. `sections` = list of (title, rows, laned)."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    drew = False
    for title, rows, laned in sections:
        if not rows:
            continue
        _draw_heat_section(c, ph, pw, 0.75 * inch, title, rows, laned)
        drew = True
    if not drew:
        c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def _fit_font(c, text, font, size, max_w, min_size=6):
    """Shrink font until text fits max_w (or hits min)."""
    while size > min_size and c.stringWidth(text, font, size) > max_w:
        size -= 0.5
    return size


def _draw_label(c, t, slot, ph, a, school_name, qr_prefix, logo=None):
    """One sticker: [logo] [big bib] [name / school / event(s)] [QR].

    Matches the reference app: full-height school logo left, big navy bib,
    name + school, optional event lines (track), QR of the bib top-right.
    """
    col = slot % t["cols"]
    row = slot // t["cols"]
    x = t["side"] * inch + col * t["px"] * inch
    y_top = ph - t["top"] * inch - row * t["py"] * inch
    lw, lh = t["lw"] * inch, t["lh"] * inch
    pad = 0.07 * inch
    top = y_top - pad
    bottom = y_top - lh + pad

    # Logo (left, vertically centered, capped so it doesn't crowd the text)
    left = x + pad
    if logo is not None:
        ls = min(lh - 2 * pad, lw * 0.24)
        cy = y_top - lh / 2
        try:
            c.drawImage(logo, left, cy - ls / 2, ls, ls,
                        preserveAspectRatio=True, mask="auto")
            left += ls + 0.08 * inch
        except Exception:  # noqa: BLE001
            pass

    # QR (top-right)
    qr_sz = min(lh * 0.4, 0.72 * inch)
    qr_text = f"{qr_prefix}{a['bib']}" if qr_prefix else str(a["bib"])
    try:
        c.drawImage(_qr_image(qr_text), x + lw - qr_sz - pad, top - qr_sz,
                    qr_sz, qr_sz, preserveAspectRatio=True, mask="auto")
    except Exception:  # noqa: BLE001
        pass

    # Big navy bib number (left column)
    big = min(lh * 0.42, 34)
    c.setFont("Helvetica-Bold", big)
    c.setFillColorRGB(*NAVY)
    bib = str(a["bib"])
    c.drawString(left, top - big * 0.8, bib)
    bib_w = c.stringWidth(bib, "Helvetica-Bold", big)
    c.setFillGray(0)

    # Text column: right of the bib, ending before the QR
    nx = left + bib_w + 0.1 * inch
    text_w = max(0.5 * inch, (x + lw - pad - qr_sz - 0.08 * inch) - nx)
    ny = top

    name = (a["name"] or "")
    nsz = _fit_font(c, name, "Helvetica-Bold", min(lh * 0.16, 15), text_w)
    c.setFont("Helvetica-Bold", nsz)
    ny -= nsz
    c.drawString(nx, ny, name)

    ssz = min(lh * 0.11, 10)
    c.setFont("Helvetica", ssz)
    c.setFillGray(0.42)
    ny -= ssz + 0.06 * inch
    c.drawString(nx, ny, (school_name or "")[:34])
    c.setFillGray(0)

    events = a.get("events") if isinstance(a, dict) else None
    if events:
        esz = min(lh * 0.13, 11)
        c.setFont("Helvetica-Bold", esz)
        for ev in events[:4]:
            ny -= esz + 0.07 * inch
            if ny < bottom:
                break
            c.drawString(nx, ny, ev[:34])


def meet_stickers_pdf(groups, *, template="5160", qr_prefix=""):
    """Meet-wide sticker sheets. `groups` = list of (school_name, logo_path, athletes).
    Each school starts on a fresh sheet (no two schools share one)."""
    t = TEMPLATES.get(template, TEMPLATES["5160"])
    per_page = t["cols"] * t["rows"]
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    _pw, ph = letter
    drew = False
    for school_name, logo_path, athletes in groups:
        items = [a for a in athletes if a["bib"] is not None]
        if not items:
            continue
        logo = _logo_reader(logo_path)
        for i, a in enumerate(items):
            slot = i % per_page
            if i and slot == 0:
                c.showPage()
            _draw_label(c, t, slot, ph, a, school_name, qr_prefix, logo)
        c.showPage()  # next school on a clean sheet
        drew = True
    if not drew:
        c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def meet_biblist_pdf(title, groups):
    """Meet-wide bib list: one titled section per school."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    left = 0.75 * inch
    y = ph - 0.9 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, title[:70])
    y -= 0.45 * inch
    for school_name, athletes in groups:
        if y < 1.4 * inch:
            c.showPage(); y = ph - 0.9 * inch
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left, y, school_name)
        y -= 0.28 * inch
        c.setFont("Helvetica", 10)
        for a in athletes:
            if y < 0.8 * inch:
                c.showPage(); y = ph - 0.9 * inch
                c.setFont("Helvetica", 10)
            bib = "" if a["bib"] is None else str(a["bib"])
            gr = "" if a["grade"] is None else f"  gr {a['grade']}"
            c.drawString(left + 0.2 * inch, y, f"{bib:>6}  {(a['name'] or '')[:38]}{gr}  {a['gender'] or ''}")
            y -= 0.22 * inch
        y -= 0.2 * inch
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
