"""Claude-powered features + document parsing (handoff §8/§9).

Phase 2 uses:
  - extract_text(): pull raw text from Excel/CSV/PDF/Word/text uploads.
  - normalize_roster(): Claude turns messy roster text into clean athlete rows.
  - google_sheet_csv_url(): turn a share link into a CSV export URL.
Later phases add vision scan-back and the insights chatbot (NB §11: timers get no AI).
"""
import csv
import io
import json
import os

CLAUDE_MODEL = os.environ.get("XC_CLAUDE_MODEL", "claude-sonnet-5")


# ------------------------- Claude client -------------------------
def _client():
    import anthropic  # imported lazily so the app boots without the key
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return anthropic.Anthropic(api_key=key)


def claude_chat(system, user, *, max_tokens=4000, model=None):
    """Single-turn helper. Returns the text of the first content block."""
    msg = _client().messages.create(
        model=model or CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def claude_vision(system, prompt, image_bytes, media_type="image/jpeg",
                  *, max_tokens=4000, model=None):
    """Vision helper: send an image + prompt, return the text response."""
    import base64
    b64 = base64.standard_b64encode(image_bytes).decode()
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
        {"type": "text", "text": prompt},
    ]
    msg = _client().messages.create(
        model=model or CLAUDE_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


_HEATSHEET_SYS = (
    "You read a photographed track & field heat sheet. Each row has a lane/section, "
    "a competitor name and/or bib, and a handwritten MARK (a time like 12.34 or "
    "2:05.4 for running events, or a distance/height like 5.42 for field events). "
    "Return ONLY a JSON array, no prose: "
    '[{"bib": <int or null>, "name": "<string or null>", "mark": "<string as written>"}]. '
    "Skip empty/illegible rows. Preserve marks exactly as written."
)


def vision_read_marks(image_bytes, media_type="image/jpeg"):
    """Read handwritten marks off a heat-sheet photo. Returns [{bib,name,mark}]."""
    out = claude_vision(_HEATSHEET_SYS, "Read this heat sheet.", image_bytes,
                        media_type=media_type, max_tokens=4000)
    rows = _find_json_array(out)
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        mark = r.get("mark")
        if mark in (None, ""):
            continue
        clean.append({"bib": r.get("bib"), "name": r.get("name"), "mark": str(mark)})
    return clean


# ------------------------- document text extraction -------------------------
def extract_text(filename, data):
    """Best-effort raw-text extraction from an uploaded roster file."""
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    if ext in ("csv", "tsv", "txt"):
        return data.decode("utf-8", "replace")
    if ext == "xlsx":
        return _xlsx_text(data)
    if ext == "xls":
        return _xls_text(data)
    if ext == "pdf":
        return _pdf_text(data)
    if ext in ("docx", "doc"):
        return _docx_text(data)
    # Unknown — try utf-8.
    return data.decode("utf-8", "replace")


def _xlsx_text(data):
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else str(c) for c in row]
            if any(cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _xls_text(data):
    import xlrd
    book = xlrd.open_workbook(file_contents=data)
    lines = []
    for sh in book.sheets():
        for r in range(sh.nrows):
            cells = [str(sh.cell_value(r, c)) for c in range(sh.ncols)]
            if any(x.strip() for x in cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _pdf_text(data):
    import pdfplumber
    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
    return "\n".join(out)


def _docx_text(data):
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs if p.text.strip()]
    for t in d.tables:
        for row in t.rows:
            cells = [c.text for c in row.cells]
            if any(x.strip() for x in cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


# ------------------------- roster normalization -------------------------
_ROSTER_SYS = (
    "You extract a cross-country / track team roster from messy text (spreadsheet "
    "dumps, PDFs, exports). Return ONLY a JSON array, no prose. Each element: "
    '{"name": "First Last", "grade": <int 6-12 or null>, "gender": "M"|"F"|null, '
    '"email": <string or null>, "phone": <string or null>, '
    '"parent_name": <string or null>, "parent_email": <string or null>, '
    '"parent_phone": <string or null>, "emergency_name": <string or null>, '
    '"emergency_phone": <string or null>}. '
    "Include the contact/parent/emergency fields ONLY when clearly present in the "
    "source (matching column headers like Email, Phone, Parent/Guardian, "
    "Emergency Contact); otherwise use null — never invent contact info. "
    "Normalize names to 'First Last' with proper capitalization. Infer gender only "
    "if explicit (a column, or M/F/Boys/Girls). Skip header rows, coaches, blanks, "
    "and totals. If a grade is given as 9th/Fr/Freshman etc., map to the integer."
)

# Optional contact fields carried through import when the source has them.
_CONTACT_FIELDS = ("email", "phone", "parent_name", "parent_email",
                   "parent_phone", "emergency_name", "emergency_phone")


def normalize_roster(raw_text, *, max_chars=20000):
    """Return a list of {name, grade, gender} dicts parsed from raw roster text."""
    text = (raw_text or "").strip()
    if not text:
        return []
    if len(text) > max_chars:
        text = text[:max_chars]
    out = claude_chat(_ROSTER_SYS, text, max_tokens=8000)
    return _parse_json_array(out)


def _find_json_array(s):
    """Locate and parse a JSON array from a model response (handles ``` fences)."""
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1]
        if s.startswith("json"):
            s = s[4:]
    a, b = s.find("["), s.rfind("]")
    if a == -1 or b == -1:
        return []
    try:
        rows = json.loads(s[a:b + 1])
    except json.JSONDecodeError:
        return []
    return rows if isinstance(rows, list) else []


def _parse_json_array(s):
    rows = _find_json_array(s)
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name", "")).strip()
        if not name:
            continue
        grade = r.get("grade")
        try:
            grade = int(grade) if grade not in (None, "") else None
        except (TypeError, ValueError):
            grade = None
        gender = r.get("gender")
        gender = gender.upper()[0] if isinstance(gender, str) and gender else None
        if gender not in ("M", "F"):
            gender = None
        row = {"name": name, "grade": grade, "gender": gender}
        for k in _CONTACT_FIELDS:
            v = r.get(k)
            row[k] = str(v).strip() if isinstance(v, (str, int)) and str(v).strip() else None
        clean.append(row)
    return clean


# ------------------------- Google Sheet -------------------------
def google_sheet_csv_url(share_url):
    """Turn a Google Sheets share/edit URL into a CSV export URL (or None)."""
    import re
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", share_url or "")
    if not m:
        return None
    sheet_id = m.group(1)
    gid = "0"
    g = re.search(r"[#&?]gid=(\d+)", share_url)
    if g:
        gid = g.group(1)
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_google_sheet_text(share_url):
    """Fetch a published/shared Google Sheet as CSV text."""
    import requests
    url = google_sheet_csv_url(share_url)
    if not url:
        raise ValueError("Not a Google Sheets URL")
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    # Normalize to tab-separated for the roster parser.
    rows = list(csv.reader(io.StringIO(r.text)))
    return "\n".join("\t".join(c for c in row) for row in rows if any(row))
