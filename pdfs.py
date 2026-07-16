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


# Athlete/timing instructions on the meet-day bib-list cover — sport-specific.
# Cross country: one race, finish chute, scan in, hand back the sticker.
_COVER_INSTRUCTIONS_XC = [
    "Place your sticker on the front of your jersey, centered on your chest.",
    "Need a blank sticker? Check in at the timing tent before your race begins.",
    "If you lose your sticker during the race, remember your bib number so you can "
    "give it to the timer at the finish.",
    "When you cross the finish line, stay in a single-file line and walk to the timing "
    "tent in the exact order you finished.",
    "Once you have been scanned in, remove your sticker and hand it to the timing crew.",
]
# Track: multiple events across the day — keep the sticker on the whole time.
_COVER_INSTRUCTIONS_TRACK = [
    "Place your sticker on the front of your jersey, centered on your chest.",
    "Need a blank sticker? Check in at the timing tent before your first event.",
    "Keep your sticker on all day — you compete in multiple events and will be scanned "
    "at each one.",
    "If you lose your sticker, remember your bib number so you can give it to the timer.",
]


def _wrap(text, font, size, max_w):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if stringWidth(trial, font, size) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_size(text, font, max_w, start, floor):
    from reportlab.pdfbase.pdfmetrics import stringWidth
    s = start
    while s > floor and stringWidth(text, font, s) > max_w:
        s -= 1
    return s


def _draw_cover(c, pw, ph, meet_name, logo, qr_img, url, instructions):
    """Welcome / instructions / results-QR cover page for the meet-day bib list."""
    cx = pw / 2.0
    y = ph - 0.7 * inch
    if logo:
        try:
            iw, ih = logo.getSize()
            sc = min((2.3 * inch) / iw, (1.4 * inch) / ih)
            w, h = iw * sc, ih * sc
            c.drawImage(logo, cx - w / 2, y - h, w, h, mask="auto")
            y -= h + 0.35 * inch
        except Exception:  # noqa: BLE001
            y -= 0.1 * inch
    else:
        y -= 0.1 * inch
    # Welcome heading (navy, shrink-to-fit)
    c.setFillColorRGB(*NAVY)
    head = f"Welcome to {meet_name}"
    hs = _fit_size(head, "Helvetica-Bold", pw - 1.4 * inch, 26, 15)
    c.setFont("Helvetica-Bold", hs)
    c.drawCentredString(cx, y, head)
    y -= 0.42 * inch
    c.setFillGray(0.35)
    c.setFont("Helvetica-Oblique", 12)
    c.drawCentredString(cx, y, "Athlete & timing instructions")
    y -= 0.5 * inch
    c.setFillGray(0)
    # Numbered, wrapped instructions
    left = 0.95 * inch
    numw = 0.34 * inch
    maxw = pw - left - 0.95 * inch - numw
    for i, text in enumerate(instructions, 1):
        c.setFont("Helvetica-Bold", 13)
        c.drawString(left, y, f"{i}.")
        c.setFont("Helvetica", 13)
        for ln in _wrap(text, "Helvetica", 13, maxw):
            c.drawString(left + numw, y, ln)
            y -= 0.245 * inch
        y -= 0.1 * inch
    y -= 0.2 * inch
    # Results + QR, centered
    c.setFillColorRGB(*NAVY)
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(cx, y, "Results can be found here")
    c.setFillGray(0)
    y -= 0.25 * inch
    if qr_img:
        qs = 1.7 * inch
        c.drawImage(qr_img, cx - qs / 2, y - qs, qs, qs)
        y -= qs + 0.02 * inch
        if url:
            c.setFont("Helvetica", 9)
            c.setFillGray(0.45)
            c.drawCentredString(cx, y, url)
            c.setFillGray(0)
    c.showPage()


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


def _draw_label_xc(c, x, y_top, lw, lh, a, school_name, qr_prefix, logo):
    """XC / no-event sticker: full-height logo left, BIG centered bib, name and
    school stacked below, QR right. The classic layout."""
    pad = 0.06 * lh
    bottom = y_top - lh
    content_l = x + pad
    if logo is not None:                       # full-height mascot on the left
        logo_w = 0.28 * lw
        try:
            c.drawImage(logo, x + pad, bottom + pad, logo_w, lh - 2 * pad,
                        preserveAspectRatio=True, anchor="w", mask="auto")
            content_l = x + pad + logo_w + 0.06 * inch
        except Exception:  # noqa: BLE001
            pass
    qr_sz = min(lh - 2 * pad, 0.30 * lw)
    qr_x = x + lw - pad - qr_sz
    code = a.get("code") if isinstance(a, dict) else None
    if code == "aruco" and isinstance(a["bib"], int) and a["bib"] <= 1023:
        # Camera-readable ArUco tag instead of the QR (bib IS the tag id).
        draw_aruco(c, qr_x, bottom + (lh - qr_sz) / 2, qr_sz, a["bib"])
    else:
        qr_text = f"{qr_prefix}{a['bib']}" if qr_prefix else str(a["bib"])
        try:
            c.drawImage(_qr_image(qr_text), qr_x, bottom + (lh - qr_sz) / 2,
                        qr_sz, qr_sz, preserveAspectRatio=True, mask="auto")
        except Exception:  # noqa: BLE001
            pass
    content_r = qr_x - 0.05 * inch
    cx = (content_l + content_r) / 2
    mw = max(0.4 * inch, content_r - content_l)

    bib = str(a["bib"])
    bibsz = _fit_font(c, bib, "Helvetica-Bold", min(lh * 0.46, 44), mw)
    c.setFont("Helvetica-Bold", bibsz)
    c.setFillColorRGB(*NAVY)
    c.drawCentredString(cx, bottom + lh * 0.50, bib)
    ntext, nsz = _fit_text(c, a["name"] or "", "Helvetica-Bold", min(lh * 0.18, 16), mw)
    c.setFont("Helvetica-Bold", nsz)
    c.setFillGray(0.1)
    c.drawCentredString(cx, bottom + lh * 0.26, ntext)
    if school_name:
        stext, ssz = _fit_text(c, school_name, "Helvetica", min(lh * 0.13, 10), mw)
        c.setFont("Helvetica", ssz)
        c.setFillGray(0.42)
        c.drawCentredString(cx, bottom + lh * 0.09, stext)
    c.setFillGray(0)


def _draw_label(c, t, slot, ph, a, school_name, qr_prefix, logo=None):
    """One sticker. No events (XC) -> big centered-bib layout; with events (track)
    -> big bib top-left + name/school beside + event lines below. QR of the bib."""
    col = slot % t["cols"]
    row = slot // t["cols"]
    x = t["side"] * inch + col * t["px"] * inch
    y_top = ph - t["top"] * inch - row * t["py"] * inch
    lw, lh = t["lw"] * inch, t["lh"] * inch
    if not (a.get("events") if isinstance(a, dict) else None):
        _draw_label_xc(c, x, y_top, lw, lh, a, school_name, qr_prefix, logo)
        return
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


def meet_biblist_pdf(title, groups, cover=None):
    """Meet-wide bib list: optional welcome/instructions/QR cover page, then one
    titled section per school. `cover` = {meet_name, logo_path, results_url}."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    if cover:
        url = cover.get("results_url")
        insts = (_COVER_INSTRUCTIONS_TRACK if cover.get("sport") == "track"
                 else _COVER_INSTRUCTIONS_XC)
        _draw_cover(c, pw, ph, cover.get("meet_name") or "",
                    _logo_reader(cover.get("logo_path")),
                    _qr_image(url) if url else None, url, insts)
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


# ------------------------------- ArUco camera tags (road prototype) -------------------------------
# Classic 5x5 ArUco markers (ids 0-1023), byte-compatible with the js-aruco
# detector on the /races/<id>/camera page: black border, data bits in columns
# 1 & 3 of each row (MSB-first, top row first), 1 = white cell.
_ARUCO_CODES = {0: (1, 0, 0, 0, 0), 1: (1, 0, 1, 1, 1),
                2: (0, 1, 0, 0, 1), 3: (0, 1, 1, 1, 0)}


def draw_aruco(c, x, y, size, marker_id):
    """Draw one marker with its lower-left corner at (x, y)."""
    cell = size / 7.0
    c.setFillColorRGB(0, 0, 0)
    c.rect(x, y, size, size, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    for row in range(5):
        pair = (marker_id >> (8 - 2 * row)) & 0b11
        bits = _ARUCO_CODES[pair]
        for col in range(5):
            if bits[col]:
                c.rect(x + (col + 1) * cell, y + size - (row + 2) * cell,
                       cell, cell, stroke=0, fill=1)


def road_tag_sheet_pdf(event_name, participants):
    """Camera-timing tag sheet: one large ArUco tag + bib + name per cell (2x3 per
    letter page). Prototype for pin-on bibs — tag-forward so the camera reads it."""
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=letter)
    pw, ph = letter
    cols, rows = 2, 3
    cw, ch = pw / cols, ph / rows
    tag = 2.3 * inch
    per_page = cols * rows
    items = [p for p in participants if p.get("bib") is not None]
    for i, p in enumerate(items):
        slot = i % per_page
        if i and slot == 0:
            c.showPage()
        col, row = slot % cols, slot // cols
        cx = col * cw + cw / 2
        top = ph - row * ch
        if p["bib"] <= 1023:
            draw_aruco(c, cx - tag / 2, top - 0.35 * inch - tag, tag, p["bib"])
        else:
            c.setFont("Helvetica", 10)
            c.setFillColorRGB(0.45, 0.45, 0.45)
            c.drawCentredString(cx, top - 1.4 * inch,
                                "(no camera tag — bib over 1023, use manual entry)")
        c.setFillColorRGB(*NAVY)
        c.setFont("Helvetica-Bold", 34)
        c.drawCentredString(cx, top - 0.35 * inch - tag - 0.55 * inch, str(p["bib"]))
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.setFont("Helvetica", 13)
        c.drawCentredString(cx, top - 0.35 * inch - tag - 0.85 * inch, p.get("name") or "")
        c.setFillColorRGB(0.55, 0.55, 0.55)
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, top - 0.35 * inch - tag - 1.05 * inch, event_name or "")
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
