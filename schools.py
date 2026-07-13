"""Schools + athletes (roster) — Phases 1-2 (handoff §8).

- School CRUD + bib blocks (admins).
- Roster: athlete CRUD, auto-bib assignment within the school's block.
- AI document import (Excel/CSV/PDF/Word -> Claude normalize -> preview -> commit).
- Google Sheet sync (share link -> CSV -> normalize).
- Bib list + Avery sticker PDFs (with QR).
- Bib check (scan QR / type bib -> athlete lookup), district-scoped.

Access: super_admin (any), district_admin (own district), coach (own schools).
Timers get no roster access.
"""
import os

from markupsafe import escape
from flask import (Blueprint, request, redirect, g, abort, jsonify, Response)

from . import db, ai, pdfs, demo
from .auth import login_required, role_required
from .tenancy import (active_district_id, require_district, scoped_district_or_403,
                      all_districts)
from .ui import shell

bp = Blueprint("schools", __name__)


def _districts_for_switcher():
    return all_districts() if g.principal.is_super else None


def _can_access_school(school):
    p = g.principal
    if not p or p.role == "timer" or p.meet_scope:
        return False
    if p.is_super:
        return True
    if p.district_id != school["district_id"]:
        return False
    if p.role == "district_admin":
        return True
    if p.role == "coach":
        return school["id"] in p.school_ids()
    return False


def _load_school_or_403(sid):
    conn = db.connect()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    conn.close()
    if not s:
        abort(404)
    if not _can_access_school(s):
        abort(403)
    return s


def _visible_schools():
    """Schools the current principal may see, newest-context-first."""
    p = g.principal
    did = active_district_id()
    conn = db.connect()
    if p.role == "coach":
        rows = conn.execute(
            "SELECT s.*, d.name AS dname FROM schools s JOIN districts d ON d.id=s.district_id "
            "JOIN user_schools us ON us.school_id=s.id WHERE us.user_id=? ORDER BY s.name",
            (p.id,),
        ).fetchall()
    elif p.is_super and did is None:
        rows = conn.execute(
            "SELECT s.*, d.name AS dname FROM schools s JOIN districts d ON d.id=s.district_id "
            "ORDER BY d.name, s.name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.*, NULL AS dname FROM schools s WHERE s.district_id=? ORDER BY s.name",
            (did,),
        ).fetchall()
    conn.close()
    return rows


def _slug(name):
    import re
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "school"


def _save_logo(file_storage, prefix):
    """Save an uploaded school logo (optimized PNG) -> '/static/logos/<name>'."""
    if not file_storage or not file_storage.filename:
        return None
    import io
    import secrets
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(file_storage.read())).convert("RGBA")
    except Exception:  # noqa: BLE001 — not a valid image
        return None
    if im.width > 400:
        im = im.resize((400, round(400 * im.height / im.width)), Image.LANCZOS)
    d = os.path.join(os.path.dirname(__file__), "static", "logos")
    os.makedirs(d, exist_ok=True)
    name = f"{_slug(prefix)}-{secrets.token_hex(4)}.png"
    im.save(os.path.join(d, name), format="PNG", optimize=True)
    return f"/static/logos/{name}"


def _next_bib(conn, school):
    """Lowest free bib within the school's block, or None if unset/full."""
    lo, hi = school["bib_start"], school["bib_end"]
    if not lo or not hi:
        return None
    used = {r[0] for r in conn.execute(
        "SELECT bib FROM athletes WHERE school_id=? AND bib IS NOT NULL", (school["id"],)
    ).fetchall()}
    for b in range(lo, hi + 1):
        if b not in used:
            return b
    return None


# ------------------------------- school list -------------------------------
@bp.get("/schools")
@login_required
def list_schools():
    p = g.principal
    if p.role == "timer" or p.meet_scope:
        abort(403)
    did = active_district_id()
    rows = _visible_schools()
    show_d = p.is_super and did is None

    hdr = ("<tr><th>School</th>" + ("<th>District</th>" if show_d else "")
           + "<th>Athletes</th><th>Bib block</th><th></th></tr>")
    conn = db.connect()
    trs = []
    for s in rows:
        n = conn.execute("SELECT COUNT(*) FROM athletes WHERE school_id=?", (s["id"],)).fetchone()[0]
        bib = f'{s["bib_start"]}&ndash;{s["bib_end"]}' if s["bib_start"] else '<span class="muted">—</span>'
        dcol = f'<td>{escape(s["dname"])}</td>' if show_d else ""
        actions = f'<a class="btn ghost" href="/schools/{s["id"]}">Open roster</a>'
        if p.is_admin:
            actions += (f' <form class="inline" method="post" action="/schools/{s["id"]}/delete" '
                        f'onsubmit="return confirm(\'Delete {escape(s["name"])} and its roster?\')">'
                        f'<button class="danger" type="submit">Delete</button></form>')
        logo = (f'<img src="{escape(s["logo_path"])}" alt="" '
                f'style="height:28px;width:28px;object-fit:contain;vertical-align:middle;margin-right:.5rem">'
                if s["logo_path"] else "")
        trs.append(f'<tr><td>{logo}<b>{escape(s["name"])}</b></td>{dcol}<td>{n}</td>'
                   f'<td>{bib}</td><td style="text-align:right">{actions}</td></tr>')
    conn.close()
    table = (f'<div class="card"><table>{hdr}{"".join(trs)}</table></div>'
             if rows else '<div class="card muted">No schools yet.</div>')

    form = ""
    if p.is_admin:
        if p.is_super and did is None:
            form = '<p class="muted">Pick a district in the header to add a school.</p>'
        else:
            form = """
<div class="card"><h2>Add a school</h2>
<form method="post" action="/schools" enctype="multipart/form-data">
  <label>Name</label><input name="name" required>
  <div class="row">
    <div><label>Bib start</label><input name="bib_start" type="number" inputmode="numeric"></div>
    <div><label>Bib end</label><input name="bib_end" type="number" inputmode="numeric"></div>
  </div>
  <label>Logo (optional)</label><input name="logo" type="file" accept="image/*">
  <button type="submit" style="margin-top:1rem">Add school</button>
</form></div>"""

    heading = "Roster" if p.role == "coach" else "Schools"
    body = f"<h1>{heading}</h1><p class='sub'>Schools, bib blocks, and rosters.</p>{table}{form}"
    return shell(p, body, active="schools",
                 active_district=did, districts=_districts_for_switcher())


@bp.post("/schools")
@role_required("super_admin", "district_admin")
def create_school():
    did = scoped_district_or_403()
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)

    def _int(v):
        v = (v or "").strip()
        return int(v) if v.lstrip("-").isdigit() else None

    logo_path = _save_logo(request.files.get("logo"), name)
    conn = db.connect()
    conn.execute(
        "INSERT INTO schools (district_id, name, bib_start, bib_end, logo_path) VALUES (?,?,?,?,?)",
        (did, name, _int(request.form.get("bib_start")), _int(request.form.get("bib_end")), logo_path),
    )
    conn.commit()
    conn.close()
    return redirect("/schools")


@bp.post("/schools/<int:sid>/edit")
@role_required("super_admin", "district_admin")
def edit_school(sid):
    s = _load_school_or_403(sid)

    def _int(v):
        v = (v or "").strip()
        return int(v) if v.lstrip("-").isdigit() else None

    name = (request.form.get("name") or "").strip() or s["name"]
    logo_path = _save_logo(request.files.get("logo"), name) or s["logo_path"]
    conn = db.connect()
    conn.execute("UPDATE schools SET name=?, bib_start=?, bib_end=?, logo_path=? WHERE id=?",
                 (name, _int(request.form.get("bib_start")), _int(request.form.get("bib_end")),
                  logo_path, sid))
    conn.commit()
    conn.close()
    return redirect(f"/schools/{sid}")


@bp.post("/schools/<int:sid>/delete")
@role_required("super_admin", "district_admin")
def delete_school(sid):
    s = _load_school_or_403(sid)
    conn = db.connect()
    conn.execute("DELETE FROM athletes WHERE school_id=?", (sid,))
    conn.execute("DELETE FROM user_schools WHERE school_id=?", (sid,))
    conn.execute("DELETE FROM schools WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return redirect("/schools")


# ------------------------------- roster -------------------------------
@bp.get("/schools/<int:sid>")
@login_required
def roster(sid):
    s = _load_school_or_403(sid)
    sport = request.args.get("sport", "all")
    grad_view = request.args.get("show") == "grad"

    where = ["school_id=?", "active=0" if grad_view else "active=1"]
    params = [sid]
    if sport == "xc":
        where.append("does_xc=1")
    elif sport == "track":
        where.append("does_track=1")
    conn = db.connect()
    ath = conn.execute(
        f"SELECT * FROM athletes WHERE {' AND '.join(where)} "
        f"ORDER BY bib IS NULL, bib, name", tuple(params)).fetchall()
    grad_count = conn.execute("SELECT COUNT(*) FROM athletes WHERE school_id=? AND active=0",
                              (sid,)).fetchone()[0]
    conn.close()

    mode = demo.mode_for(g.principal)
    ro = g.principal.is_demo
    trs = []
    for a in ath:
        nm = demo.display(a["name"], mode)
        if grad_view:
            act = "" if ro else (
                f'<form class="inline" method="post" action="/athletes/{a["id"]}/restore">'
                f'<button class="ghost" type="submit">Restore</button></form>')
            trs.append(
                f'<tr style="opacity:.7"><td>{"" if a["bib"] is None or mode=="anon" else a["bib"]}</td>'
                f'<td><b><a href="/athletes/{a["id"]}/progress">{escape(nm)}</a></b> 📈</td>'
                f'<td>{"" if a["grade"] is None else a["grade"]}</td>'
                f'<td>{a["gender"] or ""}</td>'
                f'<td style="text-align:right">{act}</td></tr>')
            continue
        dis = "disabled" if ro else ""
        xc = "checked" if a["does_xc"] else ""
        tr = "checked" if a["does_track"] else ""
        delc = "" if ro else (
            f'<form class="inline" method="post" action="/athletes/{a["id"]}/delete" '
            f'onsubmit="return confirm(\'Remove {escape(nm)}?\')">'
            f'<button class="danger" type="submit">✕</button></form>')
        trs.append(
            f'<tr><td>{"" if a["bib"] is None or mode=="anon" else a["bib"]}</td>'
            f'<td><b><a href="/athletes/{a["id"]}/progress">{escape(nm)}</a></b> 📈</td>'
            f'<td>{"" if a["grade"] is None else a["grade"]}</td>'
            f'<td>{a["gender"] or ""}</td>'
            f'<td style="text-align:center"><input type="checkbox" style="width:auto" {xc} {dis} '
            f'onchange="tog({a["id"]},\'xc\',this)"></td>'
            f'<td style="text-align:center"><input type="checkbox" style="width:auto" {tr} {dis} '
            f'onchange="tog({a["id"]},\'track\',this)"></td>'
            f'<td style="text-align:right">{delc}</td></tr>')

    if grad_view:
        head = ('<tr><th>Bib</th><th>Name</th><th>Gr</th><th>Sex</th><th></th></tr>'
                if ath else "")
        empty = "No graduated athletes."
    else:
        head = ('<tr><th>Bib</th><th>Name</th><th>Gr</th><th>Sex</th>'
                '<th style="text-align:center">XC</th><th style="text-align:center">Track</th><th></th></tr>'
                if ath else "")
        empty = "No athletes here yet — add or import below."
    table = (f'<div class="card"><table>{head}{"".join(trs)}</table></div>'
             if ath else f'<div class="card muted">{empty}</div>')

    # Sport filter + graduated toggle
    def _f(label, val):
        on = "background:var(--panel2);color:var(--fg)" if sport == val and not grad_view else ""
        return (f'<a class="btn ghost" style="{on}" '
                f'href="/schools/{sid}?sport={val}">{label}</a>')
    grad_link = (f'<a class="btn ghost" href="/schools/{sid}?show=grad" '
                 f'style="{"background:var(--panel2);color:var(--fg)" if grad_view else ""}">'
                 f'🎓 Graduated ({grad_count})</a>' if grad_count or grad_view else "")
    filt = (f'<div class="row" style="margin:.2rem 0 1rem;gap:.4rem">'
            f'{_f("All", "all")}{_f("🏃 XC", "xc")}{_f("🎽 Track", "track")}'
            f'<span style="flex:1"></span>{grad_link}</div>')

    bib_hint = (f'{s["bib_start"]}–{s["bib_end"]}' if s["bib_start"]
                else "no block set (bibs left blank)")
    logo_img = (f'<img src="{escape(s["logo_path"])}" alt="" style="height:42px;width:42px;'
                f'object-fit:contain;vertical-align:middle;margin-right:.6rem;background:#fff;'
                f'border-radius:8px;padding:3px"> ' if s["logo_path"] else "")
    body = f"""
<p class="muted"><a href="/schools">← Schools</a></p>
<h1>{logo_img}{escape(s['name'])}</h1>"""
    body += f"""
<p class="sub">{len(ath)} athletes · bib block {bib_hint}</p>

<div class="row">
  <a class="btn ghost" href="/schools/{sid}/bibs.pdf">Bib list (PDF)</a>
  <a class="btn ghost" href="/schools/{sid}/stickers.pdf?template=5160">Avery 5160 stickers</a>
  <a class="btn ghost" href="/schools/{sid}/stickers.pdf?template=5163">Avery 5163 stickers</a>
</div>
{filt}
{table}
"""
    if not ro and not grad_view:
        body += f"""
<script>
async function tog(aid, sport, el){{
  try{{ await jpost('/athletes/'+aid+'/sports', {{sport, on: el.checked}}); }}
  catch(e){{ alert(e.message); el.checked = !el.checked; }}
}}
</script>"""
    if not ro:
        body += f"""

<div class="card"><h2>Add athlete</h2>
<form method="post" action="/schools/{sid}/athletes">
  <div class="row">
    <div><label>Name</label><input name="name" required></div>
    <div style="max-width:110px"><label>Bib</label><input name="bib" type="number" placeholder="auto"></div>
    <div style="max-width:90px"><label>Grade</label><input name="grade" type="number"></div>
    <div style="max-width:110px"><label>Sex</label>
      <select name="gender"><option value="">—</option><option>M</option><option>F</option></select></div>
  </div>
  <div style="display:flex;gap:1.2rem;margin-top:.7rem">
    <label style="display:flex;gap:.4rem;align-items:center"><input type="checkbox" name="does_xc"
      value="1" checked style="width:auto"> 🏃 XC</label>
    <label style="display:flex;gap:.4rem;align-items:center"><input type="checkbox" name="does_track"
      value="1" checked style="width:auto"> 🎽 Track</label>
  </div>
  <button type="submit" style="margin-top:1rem">Add</button>
  <span class="muted">Leave bib blank to auto-assign the next free bib in the block.</span>
</form></div>

<div class="card"><h2>🎓 Start a new season</h2>
<p class="muted">Moves every athlete up one grade. Athletes finishing the top grade
graduate — kept for their stats and history, just hidden from the active roster.
Past results are never changed.</p>
<form method="post" action="/schools/{sid}/advance-season"
  onsubmit="return confirm('Advance every athlete one grade? Top-grade athletes will graduate. This can\\'t be auto-undone.')">
  <label>Top grade (these graduate)</label>
  <input name="top_grade" type="number" value="9" style="max-width:130px">
  <button type="submit" style="margin-top:.6rem">Advance season ▲</button>
</form></div>

<div class="card"><h2>Import roster</h2>
<p class="muted">Upload Excel/CSV/PDF/Word, or paste a Google Sheet link. Claude
normalizes names, then you confirm before anything is saved.</p>
<div class="row">
  <div>
    <label>File</label>
    <input type="file" id="impfile" accept=".xlsx,.xls,.csv,.tsv,.txt,.pdf,.docx">
    <button type="button" onclick="uploadImport()" style="margin-top:.6rem">Parse file</button>
  </div>
  <div>
    <label>Google Sheet share link</label>
    <input id="sheeturl" placeholder="https://docs.google.com/spreadsheets/d/...">
    <button type="button" onclick="sheetImport()" style="margin-top:.6rem">Pull sheet</button>
  </div>
</div>
<div id="preview"></div>
</div>

<script>
let PARSED = [];
function renderPreview(rows){{
  PARSED = rows || [];
  if(!PARSED.length){{ document.getElementById('preview').innerHTML =
    '<p class="msg err">No athletes found.</p>'; return; }}
  let h = '<h2>'+PARSED.length+' found — review &amp; import</h2><table>'
    +'<tr><th>Name</th><th>Gr</th><th>Sex</th></tr>';
  for(const a of PARSED) h += '<tr><td>'+esc(a.name)+'</td><td>'+esc(a.grade??'')
    +'</td><td>'+esc(a.gender??'')+'</td></tr>';
  h += '</table><button type="button" onclick="commitImport()" style="margin-top:1rem">'
    +'Import '+PARSED.length+' athletes</button>';
  document.getElementById('preview').innerHTML = h;
}}
async function uploadImport(){{
  const f = document.getElementById('impfile').files[0];
  if(!f){{ alert('Choose a file'); return; }}
  document.getElementById('preview').innerHTML = '<p class="muted">Parsing…</p>';
  const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/schools/{sid}/import/parse', {{method:'POST', body:fd}});
  const j = await r.json();
  if(!r.ok){{ document.getElementById('preview').innerHTML =
    '<p class="msg err">'+esc(j.error||'Parse failed')+'</p>'; return; }}
  renderPreview(j.athletes);
}}
async function sheetImport(){{
  const url = document.getElementById('sheeturl').value.trim();
  if(!url){{ alert('Paste a link'); return; }}
  document.getElementById('preview').innerHTML = '<p class="muted">Fetching…</p>';
  try{{ const j = await jpost('/schools/{sid}/import/sheet', {{url}}); renderPreview(j.athletes); }}
  catch(e){{ document.getElementById('preview').innerHTML =
    '<p class="msg err">'+esc(e.message)+'</p>'; }}
}}
async function commitImport(){{
  try{{ const j = await jpost('/schools/{sid}/import/commit', {{athletes: PARSED}});
    location.href = '/schools/{sid}'; }}
  catch(e){{ alert(e.message); }}
}}
</script>
"""
    if g.principal.is_admin and not ro:
        body += f"""
<div class="card"><h2>Edit school</h2>
<form method="post" action="/schools/{sid}/edit" enctype="multipart/form-data">
  <div class="row">
    <div><label>Name</label><input name="name" value="{escape(s['name'])}"></div>
    <div style="max-width:120px"><label>Bib start</label><input name="bib_start" type="number" value="{s['bib_start'] or ''}"></div>
    <div style="max-width:120px"><label>Bib end</label><input name="bib_end" type="number" value="{s['bib_end'] or ''}"></div>
  </div>
  <label>Replace logo (optional)</label><input name="logo" type="file" accept="image/*">
  <button type="submit" style="margin-top:.8rem">Save changes</button>
</form></div>"""
    return shell(g.principal, body, active="schools",
                 active_district=active_district_id(), districts=_districts_for_switcher())


@bp.post("/schools/<int:sid>/athletes")
@login_required
def add_athlete(sid):
    s = _load_school_or_403(sid)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    grade = (request.form.get("grade") or "").strip()
    grade = int(grade) if grade.isdigit() else None
    gender = (request.form.get("gender") or "").strip().upper() or None
    if gender not in ("M", "F", None):
        gender = None
    bib_raw = (request.form.get("bib") or "").strip()
    dx = 1 if request.form.get("does_xc") else 0
    dt = 1 if request.form.get("does_track") else 0
    conn = db.connect()
    bib = int(bib_raw) if bib_raw.isdigit() else _next_bib(conn, s)
    conn.execute(
        "INSERT INTO athletes (school_id, bib, name, grade, gender, does_xc, does_track) "
        "VALUES (?,?,?,?,?,?,?)",
        (sid, bib, name, grade, gender, dx, dt),
    )
    conn.commit()
    conn.close()
    return redirect(f"/schools/{sid}")


@bp.post("/athletes/<int:aid>/sports")
@login_required
def athlete_sports(aid):
    """Toggle one sport membership (XC / Track) for an athlete from the roster."""
    conn = db.connect()
    a = conn.execute("SELECT * FROM athletes WHERE id=?", (aid,)).fetchone()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (a["school_id"],)).fetchone() if a else None
    conn.close()
    if not a:
        abort(404)
    if not _can_access_school(s) or g.principal.is_demo:
        abort(403)
    data = request.get_json(silent=True) or {}
    col = {"xc": "does_xc", "track": "does_track"}.get(data.get("sport"))
    if not col:
        return jsonify(error="bad sport"), 400
    conn = db.connect()
    conn.execute(f"UPDATE athletes SET {col}=? WHERE id=?", (1 if data.get("on") else 0, aid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/athletes/<int:aid>/restore")
@login_required
def restore_athlete(aid):
    """Un-graduate an athlete (back onto the active roster)."""
    conn = db.connect()
    a = conn.execute("SELECT * FROM athletes WHERE id=?", (aid,)).fetchone()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (a["school_id"],)).fetchone() if a else None
    conn.close()
    if not a:
        abort(404)
    if not _can_access_school(s) or g.principal.is_demo:
        abort(403)
    conn = db.connect()
    conn.execute("UPDATE athletes SET active=1 WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return redirect(f"/schools/{a['school_id']}?show=grad")


@bp.post("/schools/<int:sid>/advance-season")
@login_required
def advance_season(sid):
    """New-season rollover: everyone up one grade; top-grade athletes graduate
    (active=0, kept for stats). Historical results are untouched."""
    s = _load_school_or_403(sid)
    if g.principal.is_demo:
        abort(403)
    tg = (request.form.get("top_grade") or "9").strip()
    top = int(tg) if tg.isdigit() else 9
    conn = db.connect()
    # Graduate athletes at/above the top grade first (so the bump can't push them past it).
    conn.execute("UPDATE athletes SET active=0 WHERE school_id=? AND active=1 "
                 "AND grade IS NOT NULL AND grade>=?", (sid, top))
    # Everyone else moves up one grade.
    conn.execute("UPDATE athletes SET grade=grade+1 WHERE school_id=? AND active=1 "
                 "AND grade IS NOT NULL AND grade<?", (sid, top))
    conn.commit()
    conn.close()
    return redirect(f"/schools/{sid}")


@bp.post("/athletes/<int:aid>/delete")
@login_required
def delete_athlete(aid):
    conn = db.connect()
    a = conn.execute("SELECT * FROM athletes WHERE id=?", (aid,)).fetchone()
    if not a:
        conn.close()
        abort(404)
    s = conn.execute("SELECT * FROM schools WHERE id=?", (a["school_id"],)).fetchone()
    conn.close()
    if not _can_access_school(s):
        abort(403)
    conn = db.connect()
    conn.execute("DELETE FROM athletes WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return redirect(f"/schools/{a['school_id']}")


# ------------------------------- import -------------------------------
@bp.post("/schools/<int:sid>/import/parse")
@login_required
def import_parse(sid):
    _load_school_or_403(sid)
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file uploaded"), 400
    try:
        text = ai.extract_text(f.filename, f.read())
        athletes = ai.normalize_roster(text)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not parse: {e}"), 400
    return jsonify(athletes=athletes)


@bp.post("/schools/<int:sid>/import/sheet")
@login_required
def import_sheet(sid):
    _load_school_or_403(sid)
    url = (request.get_json(silent=True) or {}).get("url", "")
    try:
        text = ai.fetch_google_sheet_text(url)
        athletes = ai.normalize_roster(text)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Could not read sheet: {e}"), 400
    return jsonify(athletes=athletes)


@bp.post("/schools/<int:sid>/import/commit")
@login_required
def import_commit(sid):
    s = _load_school_or_403(sid)
    rows = (request.get_json(silent=True) or {}).get("athletes", [])
    if not isinstance(rows, list):
        return jsonify(error="bad payload"), 400
    added = 0
    conn = db.connect()
    for r in rows:
        name = str((r or {}).get("name", "")).strip()
        if not name:
            continue
        grade = r.get("grade")
        grade = int(grade) if isinstance(grade, int) or (isinstance(grade, str) and grade.isdigit()) else None
        gender = r.get("gender")
        gender = gender if gender in ("M", "F") else None
        bib = _next_bib(conn, s)
        conn.execute(
            "INSERT INTO athletes (school_id, bib, name, grade, gender, does_xc, does_track) "
            "VALUES (?,?,?,?,?,1,1)",
            (sid, bib, name, grade, gender),
        )
        added += 1
    conn.commit()
    conn.close()
    return jsonify(added=added)


# ------------------------------- PDFs -------------------------------
def _roster_rows(sid):
    conn = db.connect()
    rows = conn.execute(
        "SELECT bib, name, grade, gender FROM athletes WHERE school_id=? AND active=1 "
        "ORDER BY bib IS NULL, bib, name", (sid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@bp.get("/schools/<int:sid>/bibs.pdf")
@login_required
def bibs_pdf(sid):
    s = _load_school_or_403(sid)
    pdf = pdfs.bib_list_pdf(s["name"], _roster_rows(sid))
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{s["name"]}-bibs.pdf"'})


@bp.get("/schools/<int:sid>/stickers.pdf")
@login_required
def stickers_pdf(sid):
    s = _load_school_or_403(sid)
    template = request.args.get("template", "5160")
    prefix = f'{os.environ.get("XC_PUBLIC_URL", "")}/bibcheck?bib='
    pdf = pdfs.bib_stickers_pdf(s["name"], _roster_rows(sid), template=template,
                                qr_prefix=prefix, logo_path=s["logo_path"])
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{s["name"]}-stickers.pdf"'})


# ------------------------------- bib check -------------------------------
@bp.get("/bibcheck")
@login_required
def bibcheck():
    """Type/scan a bib -> athlete lookup, scoped to the principal's district."""
    p = g.principal
    bib = (request.args.get("bib") or "").strip()
    result = None
    if bib.isdigit():
        did = active_district_id()
        conn = db.connect()
        if p.is_super and did is None:
            row = conn.execute(
                "SELECT a.*, s.name AS sname FROM athletes a JOIN schools s ON s.id=a.school_id "
                "WHERE a.bib=?", (int(bib),)).fetchone()
        elif p.role == "coach":
            ids = p.school_ids()
            if ids:
                q = ",".join("?" * len(ids))
                row = conn.execute(
                    f"SELECT a.*, s.name AS sname FROM athletes a JOIN schools s ON s.id=a.school_id "
                    f"WHERE a.bib=? AND a.school_id IN ({q})", (int(bib), *ids)).fetchone()
            else:
                row = None
        else:
            row = conn.execute(
                "SELECT a.*, s.name AS sname FROM athletes a JOIN schools s ON s.id=a.school_id "
                "WHERE a.bib=? AND s.district_id=?", (int(bib), did)).fetchone()
        conn.close()
        result = dict(row) if row else {}
    if request.args.get("format") == "json":
        return jsonify(result or {})

    box = ""
    if result:
        box = (f'<div class="card"><div style="font-size:1.6rem;font-weight:700">'
               f'#{result["bib"]} · {escape(result["name"])}</div>'
               f'<p class="muted">{escape(result.get("sname",""))} · '
               f'grade {result.get("grade") or "—"} · {result.get("gender") or "—"}</p></div>')
    elif bib:
        box = '<div class="msg err">No athlete with that bib in your scope.</div>'
    body = f"""
<h1>Bib check</h1><p class="sub">Scan a sticker QR or type a bib number.</p>
<div class="card"><form method="get" action="/bibcheck">
  <label>Bib number</label><input name="bib" type="number" autofocus value="{escape(bib)}">
  <button type="submit" style="margin-top:1rem">Look up</button>
</form></div>{box}"""
    return shell(p, body, active="", active_district=active_district_id(),
                 districts=_districts_for_switcher())
