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


def _draw_label(c, t, slot, ph, a, school_name, qr_prefix):
    col = slot % t["cols"]
    row = slot // t["cols"]
    x = t["side"] * inch + col * t["px"] * inch
    y_top = ph - t["top"] * inch - row * t["py"] * inch
    lw, lh = t["lw"] * inch, t["lh"] * inch
    pad = 0.08 * inch
    qr_sz = min(lh - 2 * pad, 0.8 * inch)
    qr_text = f"{qr_prefix}{a['bib']}" if qr_prefix else str(a["bib"])
    try:
        c.drawImage(_qr_image(qr_text), x + lw - qr_sz - pad, y_top - qr_sz - pad,
                    qr_sz, qr_sz, preserveAspectRatio=True, mask="auto")
    except Exception:  # noqa: BLE001
        pass
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x + pad, y_top - 0.34 * inch, f"#{a['bib']}")
    c.setFont("Helvetica", 10)
    c.drawString(x + pad, y_top - 0.54 * inch, (a["name"] or "")[:26])
    c.setFont("Helvetica", 7)
    c.setFillGray(0.4)
    c.drawString(x + pad, y_top - 0.70 * inch, (school_name or "")[:32])
    c.setFillGray(0)


def meet_stickers_pdf(groups, *, template="5160", qr_prefix=""):
    """Meet-wide sticker sheets. `groups` = list of (school_name, athletes).
    Each school starts on a fresh sheet (no two schools share one)."""
    t = TEMPLATES.get(template, TEMPLATES["5160"])
    per_page = t["cols"] * t["rows"]
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    _pw, ph = letter
    drew = False
    for school_name, athletes in groups:
        items = [a for a in athletes if a["bib"] is not None]
        if not items:
            continue
        for i, a in enumerate(items):
            slot = i % per_page
            if i and slot == 0:
                c.showPage()
            _draw_label(c, t, slot, ph, a, school_name, qr_prefix)
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
