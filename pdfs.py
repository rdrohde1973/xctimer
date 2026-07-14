"""PDF generation with reportlab (handoff §8). Phase 2: bib stickers + bib lists.

Later phases add heat sheets / meet-day packets (track).
"""
import io
import os

from reportlab.lib.pagesizes import letter, landscape
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


def per_page(template):
    t = TEMPLATES.get(template, TEMPLATES["5160"])
    return t["cols"] * t["rows"]


def blank_fillers(used_bibs, bib_start, bib_end, need):
    """`need` blank sticker rows (name='') carrying the next available bib numbers
    within the school's block — leftover labels become ready-to-use last-minute adds."""
    if need <= 0:
        return []
    used = {b for b in used_bibs if b is not None}
    nb = max(used) + 1 if used else (bib_start or 1)
    if bib_start and nb < bib_start:
        nb = bib_start
    out, b = [], nb
    while len(out) < need:
        if bib_end and b > bib_end:      # don't spill past this school's block
            break
        if b not in used:
            out.append({"bib": b, "name": "", "grade": None, "gender": None})
            used.add(b)
        b += 1
    return out


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


_HOWTO = {
    "track": "HOW TO RECORD: write each athlete's finish TIME (e.g. 1:02.34), then photograph this sheet on the Scan tab.",
    "field": "HOW TO RECORD: write each of the 3 attempts (F = foul); the best legal mark scores. Then scan this sheet.",
    "hj": "HOW TO RECORD: mark each bar — O=clear, X=miss (XO/XXO), XXX=out. Highest bar cleared scores (BEST box optional). Then scan.",
}


def _draw_token(c, ph, pw, token):
    """QR + token text in the top-right corner (lets the scanner auto-ID the sheet)."""
    if not token:
        return
    try:
        c.drawImage(_qr_image(token), pw - 1.15 * inch, ph - 1.2 * inch, 0.72 * inch, 0.72 * inch,
                    preserveAspectRatio=True, mask="auto")
    except Exception:  # noqa: BLE001
        pass
    c.setFont("Helvetica", 7)
    c.setFillGray(0.45)
    c.drawRightString(pw - 0.42 * inch, ph - 1.33 * inch, token)
    c.setFillGray(0)


def _draw_heat_section(c, ph, pw, left, title, rows, laned, token=None):
    """Draw one running event's heats (one heat/section per page) onto canvas `c`."""
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
        c.drawString(left, y, title[:60])
        _draw_token(c, ph, pw, token)
        y -= 0.28 * inch
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left, y, f"{unit} {heat}")
        y -= 0.24 * inch
        c.setFont("Helvetica", 8)
        c.setFillGray(0.4)
        c.drawString(left, y, _HOWTO["track"])
        c.setFillGray(0)
        y -= 0.26 * inch
        c.setFont("Helvetica-Bold", 9)
        c.setFillGray(0.35)
        cols = ([("LANE", 0)] if laned else [("ORDER", 0)]) + \
               [("BIB", 0.7 * inch), ("NAME", 1.4 * inch), ("MARK / TIME", 4.3 * inch)]
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
            c.drawString(left, y, str(r["lane"] or ""))
            c.drawString(left + 0.7 * inch, y, "" if r["bib"] is None else str(r["bib"]))
            c.drawString(left + 1.4 * inch, y, (r["name"] or "")[:34])
            c.line(left + 4.3 * inch, y - 0.02 * inch, pw - 0.6 * inch, y - 0.02 * inch)
            y -= 0.34 * inch
        # blank rows for last-minute additions
        for _ in range(2):
            c.line(left + 4.3 * inch, y - 0.02 * inch, pw - 0.6 * inch, y - 0.02 * inch)
            y -= 0.34 * inch
        c.showPage()


def _draw_field_section(c, ph, pw, left, title, rows, hj, token=None, bars=None):
    """One page for a field event: LJ/SP 3-attempt boxes, or HJ make/miss bar grid.
    HJ uses big boxes and prints the bar heights (if known) so it scans cleanly."""
    bars = [b for b in (bars or []) if b]
    y = ph - 0.9 * inch
    c.setFont("Helvetica-Bold", 16)
    c.drawString(left, y, title[:60])
    _draw_token(c, ph, pw, token)
    y -= 0.28 * inch
    c.setFont("Helvetica", 8)
    c.setFillGray(0.4)
    c.drawString(left, y, _HOWTO["hj"] if hj else _HOWTO["field"])
    c.setFillGray(0)

    if hj:
        # High Jump jury grid: the pre-set bar heights print as columns (mark O/X/P
        # per height); a wide BEST box on the right is what the scanner reads.
        name_x = left + 0.5 * inch
        hx = name_x + 1.7 * inch
        best_w = 1.1 * inch                    # wide target — this is what the scanner reads
        right_edge = pw - 0.5 * inch
        hcols = bars[:16]                       # landscape fits a full ladder
        avail = right_edge - best_w - 0.2 * inch - hx
        cw = max(0.38 * inch, min(0.52 * inch, avail / len(hcols))) if hcols else 0.45 * inch
        best_x = hx + len(hcols) * cw + 0.15 * inch
        y -= 0.36 * inch
        c.setFont("Helvetica-Bold", 8)
        c.setFillGray(0.35)
        c.drawString(left, y, "BIB")
        c.drawString(name_x, y, "NAME")
        for i, b in enumerate(hcols):
            c.drawCentredString(hx + i * cw + cw / 2, y, b)
        c.drawString(best_x, y, "BEST")
        c.setFillGray(0)
        y -= 0.12 * inch
        c.line(left, y, right_edge, y)
        y -= 0.4 * inch
        for r in list(rows) + [None] * 3:
            if y < 0.9 * inch:
                c.showPage()
                y = ph - 0.9 * inch
            c.setFont("Helvetica", 10)
            if r:
                c.drawString(left, y, "" if r["bib"] is None else str(r["bib"]))
                c.drawString(name_x, y, (r["name"] or "")[:20])
            for i in range(len(hcols)):
                c.rect(hx + i * cw, y - 0.1 * inch, cw - 0.04 * inch, 0.32 * inch)
            c.rect(best_x, y - 0.1 * inch, best_w, 0.32 * inch)
            y -= 0.5 * inch
        c.showPage()
        return

    # Long Jump / Shot Put: three attempt boxes per athlete.
    name_x, gx = left + 0.7 * inch, left + 4.5 * inch
    y -= 0.34 * inch
    c.setFont("Helvetica-Bold", 9)
    c.setFillGray(0.35)
    c.drawString(left, y, "BIB")
    c.drawString(name_x, y, "NAME")
    c.setFillGray(0)
    c.setFont("Helvetica-Bold", 9)
    for i, lbl in enumerate(("ATT 1", "ATT 2", "ATT 3")):
        c.drawString(gx + i * 0.85 * inch, y, lbl)
    y -= 0.14 * inch
    c.line(left, y, pw - 0.5 * inch, y)
    y -= 0.3 * inch

    for r in list(rows) + [None] * 3:  # blank rows for additions
        if y < 0.9 * inch:
            c.showPage()
            y = ph - 0.9 * inch
        c.setFont("Helvetica", 11)
        if r:
            c.drawString(left, y, "" if r["bib"] is None else str(r["bib"]))
            c.drawString(name_x, y, (r["name"] or "")[:40])
        for i in range(3):
            c.rect(gx + i * 0.85 * inch, y - 0.05 * inch, 0.7 * inch, 0.26 * inch)
        y -= 0.42 * inch
    c.showPage()


def heat_sheet_pdf(title, rows, *, laned=True, token=None, kind="track", bars=None):
    """Meet-day packet for one event. kind: 'track' | 'field' | 'hj'.
    High Jump prints landscape so the whole bar ladder + BEST box fit with room."""
    buf = io.BytesIO()
    page = landscape(letter) if kind == "hj" else letter
    c = pdfcanvas.Canvas(buf, pagesize=page)
    pw, ph = page
    if kind in ("field", "hj"):
        _draw_field_section(c, ph, pw, 0.75 * inch, title, rows, kind == "hj", token, bars)
    else:
        _draw_heat_section(c, ph, pw, 0.75 * inch, title, rows, laned, token)
    c.save()
    buf.seek(0)
    return buf.read()


def multi_heat_sheet_pdf(sections):
    """Meet-wide sheets. `sections` = list of (title, rows, laned, token, kind)."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    drew = False
    for sec in sections:
        title, rows, laned = sec[0], sec[1], sec[2]
        token = sec[3] if len(sec) > 3 else None
        kind = sec[4] if len(sec) > 4 else "track"
        bars = sec[5] if len(sec) > 5 else None
        if not rows:
            continue
        if kind == "hj":                       # landscape page for the bar ladder
            lpw, lph = landscape(letter)
            c.setPageSize((lpw, lph))
            _draw_field_section(c, lph, lpw, 0.75 * inch, title, rows, True, token, bars)
            c.setPageSize(letter)              # back to portrait for the next section
        elif kind == "field":
            _draw_field_section(c, ph, pw, 0.75 * inch, title, rows, False, token, bars)
        else:
            _draw_heat_section(c, ph, pw, 0.75 * inch, title, rows, laned, token)
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


def _fit_text(c, text, font, size, max_w, min_size=6):
    """Shrink font, then truncate with an ellipsis so it can never exceed max_w."""
    text = text or ""
    size = _fit_font(c, text, font, size, max_w, min_size)
    if c.stringWidth(text, font, size) > max_w:
        while text and c.stringWidth(text + "…", font, size) > max_w:
            text = text[:-1]
        text = (text + "…") if text else ""
    return text, size


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

    # QR (top-right corner)
    qr_sz = min(lh * 0.5, 0.72 * inch)
    qr_text = f"{qr_prefix}{a['bib']}" if qr_prefix else str(a["bib"])
    qr_x = x + lw - qr_sz - pad
    try:
        c.drawImage(_qr_image(qr_text), qr_x, top - qr_sz,
                    qr_sz, qr_sz, preserveAspectRatio=True, mask="auto")
    except Exception:  # noqa: BLE001
        pass

    content_l = left
    content_r = qr_x - 0.07 * inch
    content_w = max(0.6 * inch, content_r - content_l)

    # Header row: big navy bib top-left, name + school stacked to its right.
    bib = str(a["bib"])
    bibsz = min(lh * 0.48, 36)
    while bibsz > 14 and c.stringWidth(bib, "Helvetica-Bold", bibsz) > content_w * 0.42:
        bibsz -= 1
    bib_base = top - bibsz * 0.82
    c.setFont("Helvetica-Bold", bibsz)
    c.setFillColorRGB(*NAVY)
    c.drawString(content_l, bib_base, bib)
    bibw = c.stringWidth(bib, "Helvetica-Bold", bibsz)

    name_x = content_l + bibw + 0.1 * inch
    name_w = max(0.5 * inch, content_r - name_x)
    ntext, nsz = _fit_text(c, a["name"] or "", "Helvetica-Bold", min(lh * 0.2, 14), name_w)
    c.setFont("Helvetica-Bold", nsz)
    c.setFillColorRGB(*NAVY)
    c.drawString(name_x, top - nsz, ntext)
    if school_name:
        stext, ssz = _fit_text(c, school_name, "Helvetica", min(lh * 0.13, 9.5), name_w)
        c.setFont("Helvetica", ssz)
        c.setFillGray(0.45)
        c.drawString(name_x, top - nsz - ssz - 0.03 * inch, stext)

    # Body: event lines, left-aligned under the bib.
    events = a.get("events") if isinstance(a, dict) else None
    events = (events or [])[:4]
    if events:
        avail = (bib_base - 0.07 * inch) - bottom
        esz = min(lh * 0.14, 9.5)
        line_gap = 0.035 * inch
        need = len(events) * esz + (len(events) - 1) * line_gap
        if need > avail and avail > 0:
            sf = avail / need
            esz *= sf
            line_gap *= sf
        cursor = bib_base - 0.07 * inch
        for ev in events:
            etext, e_ = _fit_text(c, ev, "Helvetica-Bold", esz, content_w)
            cursor -= e_
            if cursor < bottom:
                break
            c.setFont("Helvetica-Bold", e_)
            c.setFillGray(0)
            c.drawString(content_l, cursor, etext)
            cursor -= line_gap
    c.setFillGray(0)


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
            evs = a.get("events") if isinstance(a, dict) else None
            if evs:  # the coach's day-of checklist: what each athlete is entered in
                c.setFont("Helvetica", 8)
                c.setFillGray(0.4)
                c.drawString(left + 1.15 * inch, y - 0.15 * inch, ("; ".join(evs))[:110])
                c.setFillGray(0)
                c.setFont("Helvetica", 10)
                y -= 0.16 * inch
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
