"""Track & field engine (handoff §8). Reference: ~/track/track_timer.py.

Events (grade x gender), entries (individual + relay), seeded/random heat & lane
draws, marks entry (track times + field attempts, incl. High Jump), per-event
placing + points-table scoring, team totals, heat-sheet PDFs, public results,
and AI vision scan-back of a photographed heat sheet.

Deferred refinements (noted, not blocking a runnable meet): athlete-centric bulk
assignment UI, carry-over from last meet, combined distance races, open-pit HJ,
full bar-by-bar HJ make/miss grid (we record best height cleared).
"""
import io
import json
import random

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, jsonify, Response

from . import db, ai, pdfs, demo
from .auth import login_required
from .tenancy import active_district_id, all_districts
from .ui import shell
from .meets import load_meet, can_view_meet, can_setup_meet, can_record_meet

bp = Blueprint("track", __name__)

DEFAULT_EVENT_LIMIT = 4
DEFAULT_LANES = 8
DEFAULT_SECTION = 16


# ------------------------------- helpers -------------------------------
def _districts_for_switcher():
    return all_districts() if g.principal.is_super else None


def parse_time(s):
    """'2:05.4' or '12.34' -> seconds (float), or None."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            m, rest = s.split(":", 1)
            return int(m) * 60 + float(rest)
        return float(s)
    except ValueError:
        return None


def fmt_time(sec):
    if sec is None:
        return ""
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m}:{s:05.2f}" if m else f"{s:.2f}"


def parse_metric(s):
    s = (s or "").strip()
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def fmt_metric(v):
    return "" if v is None else f"{v:.2f}m"


def lane_order(n):
    """Center-out lane preference, e.g. n=8 -> [4,5,3,6,2,7,1,8]."""
    seq, a, b, toggle = [], (n + 1) // 2, (n + 1) // 2 + 1, True
    while len(seq) < n:
        if toggle and a >= 1:
            seq.append(a); a -= 1
        elif b <= n:
            seq.append(b); b += 1
        elif a >= 1:
            seq.append(a); a -= 1
        toggle = not toggle
    return seq


def points_tables():
    conn = db.connect()
    rows = {r["name"]: json.loads(r["point_values_json"])
            for r in conn.execute("SELECT name, point_values_json FROM points_tables").fetchall()}
    conn.close()
    ind = rows.get("Individual (1-8)", [10, 8, 6, 5, 4, 3, 2, 1])
    rel = rows.get("Relay (1-8)", [20, 16, 12, 10, 8, 6, 4, 2])
    return ind, rel


def event_limit(meet):
    try:
        return int(json.loads(meet["settings_json"] or "{}").get("event_limit", DEFAULT_EVENT_LIMIT))
    except (ValueError, TypeError):
        return DEFAULT_EVENT_LIMIT


def _event_kind(ev):
    return ev["kind"]  # track | field | relay


def _is_hj(ev):
    return ev["ename"] == "High Jump"


def load_meet_event(meid):
    conn = db.connect()
    row = conn.execute(
        "SELECT me.*, e.name AS ename, e.kind, e.unit, e.laned, e.scoring_order, e.sort "
        "FROM meet_events me JOIN events e ON e.id=me.event_id WHERE me.id=?", (meid,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    return row


# ------------------------------- events management -------------------------------
@bp.get("/meets/<int:mid>/events")
@login_required
def meet_events(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    setup = can_setup_meet(m)
    conn = db.connect()
    catalog = conn.execute("SELECT * FROM events ORDER BY sort").fetchall()
    mes = conn.execute(
        "SELECT me.*, e.name AS ename, e.kind FROM meet_events me JOIN events e ON e.id=me.event_id "
        "WHERE me.meet_id=? ORDER BY e.sort, me.gender", (mid,)).fetchall()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT me.id, COUNT(en.id) FROM meet_events me LEFT JOIN entries en ON en.meet_event_id=me.id "
        "WHERE me.meet_id=? GROUP BY me.id", (mid,)).fetchall()}
    conn.close()

    trs = []
    for me in mes:
        g_ = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open")
        gr = f' · G{me["grade"]}' if me["grade"] else ""
        rm = (f'<form class="inline" method="post" action="/meet-events/{me["id"]}/delete" '
              f'onsubmit="return confirm(\'Remove event?\')"><button class="danger">✕</button></form>'
              if setup else "")
        trs.append(f'<tr><td><b><a href="/meet-events/{me["id"]}">{escape(me["ename"])}</a></b></td>'
                   f'<td>{g_}{gr}</td><td>{counts.get(me["id"],0)} entries</td>'
                   f'<td style="text-align:right">{rm}</td></tr>')
    table = (f'<div class="card"><table><tr><th>Event</th><th>Division</th><th></th><th></th></tr>'
             f'{"".join(trs)}</table></div>' if mes else '<div class="card muted">No events yet.</div>')

    forms = ""
    if setup:
        opts = "".join(f'<option value="{e["id"]}">{escape(e["name"])}</option>' for e in catalog)
        forms = f"""
<div class="card"><h2>Add event</h2>
<form method="post" action="/meets/{mid}/events" class="row">
  <div><label>Event</label><select name="event_id">{opts}</select></div>
  <div style="max-width:130px"><label>Division</label>
    <select name="gender"><option value="M">Boys</option><option value="F">Girls</option>
    <option value="">Open</option></select></div>
  <div style="max-width:110px"><label>Grade</label><input name="grade" type="number" placeholder="any"></div>
  <div style="max-width:110px;display:flex;align-items:flex-end"><button type="submit">Add</button></div>
</form></div>
<div class="card"><h2>Meet settings</h2>
<form method="post" action="/meets/{mid}/settings" class="row">
  <div style="max-width:200px"><label>Per-athlete event limit</label>
    <input name="event_limit" type="number" value="{event_limit(m)}"></div>
  <div style="max-width:120px;display:flex;align-items:flex-end"><button type="submit">Save</button></div>
</form></div>"""

    body = (f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
            f'<h1>{escape(m["name"])} — Events</h1>'
            f'<p class="sub">Add events, then open each to enter athletes and seed heats.</p>'
            f'{table}{forms}')
    return shell(g.principal, body, active="meets",
                 active_district=active_district_id(), districts=_districts_for_switcher())


@bp.post("/meets/<int:mid>/events")
@login_required
def add_meet_event(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    eid = request.form.get("event_id")
    if not (eid or "").isdigit():
        abort(400)
    gender = request.form.get("gender") if request.form.get("gender") in ("M", "F") else None
    grade = request.form.get("grade")
    grade = int(grade) if (grade or "").isdigit() else None
    conn = db.connect()
    conn.execute("INSERT INTO meet_events (meet_id, event_id, gender, grade) VALUES (?,?,?,?)",
                 (mid, int(eid), gender, grade))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}/events")


@bp.post("/meets/<int:mid>/settings")
@login_required
def meet_settings(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    lim = request.form.get("event_limit")
    settings = json.loads(m["settings_json"] or "{}")
    if (lim or "").isdigit():
        settings["event_limit"] = int(lim)
    conn = db.connect()
    conn.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps(settings), mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}/events")


@bp.post("/meet-events/<int:meid>/delete")
@login_required
def delete_meet_event(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_setup_meet(m):
        abort(403)
    conn = db.connect()
    conn.execute("DELETE FROM results WHERE entry_id IN (SELECT id FROM entries WHERE meet_event_id=?)", (meid,))
    conn.execute("DELETE FROM entries WHERE meet_event_id=?", (meid,))
    conn.execute("DELETE FROM meet_events WHERE id=?", (meid,))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{me['meet_id']}/events")


# ------------------------------- entries -------------------------------
def _attending_athletes(conn, mid, gender=None, grade=None):
    q = ("SELECT a.*, s.name AS sname FROM athletes a JOIN schools s ON s.id=a.school_id "
         "JOIN meet_schools ms ON ms.school_id=a.school_id WHERE ms.meet_id=?")
    args = [mid]
    if gender:
        q += " AND a.gender=?"; args.append(gender)
    if grade:
        q += " AND a.grade=?"; args.append(grade)
    q += " ORDER BY s.name, a.name"
    return conn.execute(q, args).fetchall()


def _attending_schools(conn, mid):
    return conn.execute(
        "SELECT s.* FROM schools s JOIN meet_schools ms ON ms.school_id=s.id "
        "WHERE ms.meet_id=? ORDER BY s.name", (mid,)).fetchall()


@bp.post("/meet-events/<int:meid>/entries")
@login_required
def add_entry(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_setup_meet(m):
        abort(403)
    conn = db.connect()
    seed = parse_time(request.form.get("seed")) if me["unit"] == "seconds" \
        else parse_metric(request.form.get("seed"))
    if me["kind"] == "relay":
        sid = request.form.get("school_id")
        if not (sid or "").isdigit():
            conn.close(); abort(400)
        label = (request.form.get("relay_label") or "A").strip()
        members = [x.strip() for x in (request.form.get("members") or "").split(",") if x.strip()]
        conn.execute(
            "INSERT INTO entries (meet_event_id, school_id, relay_label, members_json, seed) "
            "VALUES (?,?,?,?,?)", (meid, int(sid), label, json.dumps(members), seed))
    else:
        aid = request.form.get("runner_id")
        if not (aid or "").isdigit():
            conn.close(); abort(400)
        a = conn.execute("SELECT * FROM athletes a WHERE id=?", (int(aid),)).fetchone()
        if not a:
            conn.close(); abort(404)
        # Enforce per-athlete event limit across this meet.
        used = conn.execute(
            "SELECT COUNT(*) FROM entries en JOIN meet_events me ON me.id=en.meet_event_id "
            "WHERE me.meet_id=? AND en.runner_id=?", (me["meet_id"], int(aid))).fetchone()[0]
        if used >= event_limit(m):
            conn.close()
            return redirect(f"/meet-events/{meid}?err=limit")
        conn.execute(
            "INSERT INTO entries (meet_event_id, runner_id, school_id, seed) VALUES (?,?,?,?)",
            (meid, int(aid), a["school_id"], seed))
    conn.commit()
    conn.close()
    return redirect(f"/meet-events/{meid}")


@bp.post("/entries/<int:eid>/delete")
@login_required
def delete_entry(eid):
    conn = db.connect()
    e = conn.execute("SELECT * FROM entries WHERE id=?", (eid,)).fetchone()
    conn.close()
    if not e:
        abort(404)
    me = load_meet_event(e["meet_event_id"])
    m = load_meet(me["meet_id"])
    if not can_setup_meet(m):
        abort(403)
    conn = db.connect()
    conn.execute("DELETE FROM results WHERE entry_id=?", (eid,))
    conn.execute("DELETE FROM entries WHERE id=?", (eid,))
    conn.commit()
    conn.close()
    return redirect(f"/meet-events/{e['meet_event_id']}")


# ------------------------------- seeding -------------------------------
@bp.post("/meet-events/<int:meid>/seed")
@login_required
def seed_event(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_setup_meet(m):
        abort(403)
    mode = request.form.get("mode", "seeded")
    laned = bool(me["laned"])
    size = DEFAULT_LANES if laned else DEFAULT_SECTION
    conn = db.connect()
    entries = conn.execute("SELECT * FROM entries WHERE meet_event_id=?", (meid,)).fetchall()
    entries = list(entries)
    if mode == "random":
        random.shuffle(entries)
    else:  # seeded: fastest/best first (times asc; field marks desc)
        INF = float("inf")
        if me["scoring_order"] == "asc":
            entries.sort(key=lambda e: e["seed"] if e["seed"] is not None else INF)
        else:
            entries.sort(key=lambda e: -(e["seed"] if e["seed"] is not None else -INF))
    n = len(entries)
    groups = [entries[i:i + size] for i in range(0, n, size)] or []
    H = len(groups)
    for gi, grp in enumerate(groups):
        heat_no = H - gi  # fastest group in the last (highest) heat/section
        # Center-out within the full lane count (e.g. 4 runners -> lanes 4,5,3,6).
        lanes = lane_order(size)[:len(grp)] if laned else [None] * len(grp)
        for idx, e in enumerate(grp):
            conn.execute("UPDATE entries SET heat=?, lane=? WHERE id=?",
                         (heat_no, lanes[idx], e["id"]))
    conn.commit()
    conn.close()
    return redirect(f"/meet-events/{meid}")


# ------------------------------- marks + placing -------------------------------
def _entry_label(conn, e):
    if e["runner_id"]:
        a = conn.execute("SELECT a.name, a.bib, s.name AS sname FROM athletes a "
                         "JOIN schools s ON s.id=a.school_id WHERE a.id=?", (e["runner_id"],)).fetchone()
        if a:
            return a["name"], a["bib"], a["sname"]
        return "—", None, None
    s = conn.execute("SELECT name FROM schools WHERE id=?", (e["school_id"],)).fetchone()
    return f'{s["name"] if s else "?"} {e["relay_label"] or ""}'.strip(), None, s["name"] if s else None


def _recompute_places(conn, me):
    """Rank results for a meet_event and write place numbers."""
    rows = conn.execute(
        "SELECT r.*, e.meet_event_id FROM results r JOIN entries e ON e.id=r.entry_id "
        "WHERE e.meet_event_id=?", (me["id"],)).fetchall()
    scored = []
    for r in rows:
        if r["dq"]:
            continue
        mark = r["mark_seconds"] if me["unit"] == "seconds" else r["mark_metric"]
        if mark is None:
            continue
        scored.append((mark, r["id"]))
    reverse = me["scoring_order"] == "desc"
    scored.sort(key=lambda x: x[0], reverse=reverse)
    for i, (_, rid) in enumerate(scored):
        conn.execute("UPDATE results SET place=? WHERE id=?", (i + 1, rid))
    # Clear place on DQ/no-mark rows
    keep = {rid for _, rid in scored}
    for r in rows:
        if r["id"] not in keep:
            conn.execute("UPDATE results SET place=NULL WHERE id=?", (r["id"],))


@bp.post("/meet-events/<int:meid>/marks")
@login_required
def save_marks(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_record_meet(m):
        abort(403)
    conn = db.connect()
    entries = conn.execute("SELECT * FROM entries WHERE meet_event_id=?", (meid,)).fetchall()
    hj = _is_hj(me)
    for e in entries:
        eid = e["id"]
        dq = 1 if request.form.get(f"dq_{eid}") else 0
        mark_seconds = mark_metric = None
        attempts = None
        if me["unit"] == "seconds":
            mark_seconds = parse_time(request.form.get(f"mark_{eid}"))
        elif hj:
            mark_metric = parse_metric(request.form.get(f"mark_{eid}"))
        else:  # LJ / SP: three attempts, best legal
            atts = [parse_metric(request.form.get(f"a{n}_{eid}")) for n in (1, 2, 3)]
            attempts = atts
            legal = [x for x in atts if x is not None]
            mark_metric = max(legal) if legal else None
        name, bib, school = _entry_label(conn, e)
        conn.execute("DELETE FROM results WHERE entry_id=?", (eid,))
        conn.execute(
            "INSERT INTO results (entry_id, mark_seconds, mark_metric, attempts_json, dq, "
            "snap_name, snap_bib, snap_school) VALUES (?,?,?,?,?,?,?,?)",
            (eid, mark_seconds, mark_metric, json.dumps(attempts) if attempts else None,
             dq, name, bib, school))
    _recompute_places(conn, me)
    conn.commit()
    conn.close()
    return redirect(f"/meet-events/{meid}")


# ------------------------------- event page -------------------------------
@bp.get("/meet-events/<int:meid>")
@login_required
def event_page(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_view_meet(m):
        abort(403)
    record = can_record_meet(m)
    setup = can_setup_meet(m)
    hj = _is_hj(me)
    conn = db.connect()
    entries = conn.execute(
        "SELECT * FROM entries WHERE meet_event_id=? ORDER BY heat, lane, id", (meid,)).fetchall()
    res = {r["entry_id"]: r for r in conn.execute(
        "SELECT r.* FROM results r JOIN entries e ON e.id=r.entry_id WHERE e.meet_event_id=?",
        (meid,)).fetchall()}
    labels = {e["id"]: _entry_label(conn, e) for e in entries}
    athletes = _attending_athletes(conn, me["meet_id"], me["gender"], me["grade"]) \
        if me["kind"] != "relay" else []
    schools = _attending_schools(conn, me["meet_id"]) if me["kind"] == "relay" else []
    conn.close()

    div = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open")
    ename = f'{me["ename"]} — {div}' + (f' (G{me["grade"]})' if me["grade"] else "")
    err = '<div class="msg err">That athlete has hit the meet event limit.</div>' \
        if request.args.get("err") == "limit" else ""

    # Entries + marks form
    def mark_cell(e):
        r = res.get(e["id"])
        if me["unit"] == "seconds":
            v = fmt_time(r["mark_seconds"]) if r and r["mark_seconds"] is not None else ""
            return f'<input name="mark_{e["id"]}" value="{v}" placeholder="mm:ss.t / s.t" style="width:110px">'
        if hj:
            v = f'{r["mark_metric"]:.2f}' if r and r["mark_metric"] is not None else ""
            return f'<input name="mark_{e["id"]}" value="{v}" placeholder="height m" style="width:90px">'
        atts = json.loads(r["attempts_json"]) if r and r["attempts_json"] else [None, None, None]
        cells = "".join(
            f'<input name="a{n}_{e["id"]}" value="{("%.2f"%atts[n-1]) if atts[n-1] is not None else ""}" '
            f'placeholder="A{n}" style="width:62px">' for n in (1, 2, 3))
        return cells

    rows = []
    for e in entries:
        name, bib, school = labels[e["id"]]
        r = res.get(e["id"])
        place = r["place"] if r and r["place"] else ""
        dqc = f'<input type="checkbox" name="dq_{e["id"]}" style="width:auto" {"checked" if r and r["dq"] else ""}>'
        hl = f'{e["heat"] or ""}' + (f'/{e["lane"]}' if e["lane"] else "")
        delc = (f'<form class="inline" method="post" action="/entries/{e["id"]}/delete">'
                f'<button class="danger">✕</button></form>' if setup else "")
        rows.append(
            f'<tr><td>{place}</td><td class="muted">{hl}</td>'
            f'<td><b>{escape(name)}</b>{f" #{bib}" if bib else ""}<br>'
            f'<span class="muted">{escape(school or "")}</span></td>'
            f'<td>{mark_cell(e)}</td><td>{dqc}</td><td>{delc}</td></tr>')
    marks_form = ""
    if entries:
        inner = (f'<table><tr><th>Pl</th><th>Ht/Ln</th><th>Competitor</th>'
                 f'<th>{"Attempts (best counts)" if me["kind"]!="relay" and me["unit"]=="metric" and not hj else ("Height" if hj else "Mark/Time")}</th>'
                 f'<th>DQ</th><th></th></tr>{"".join(rows)}</table>')
        if record:
            marks_form = (f'<form method="post" action="/meet-events/{meid}/marks">'
                          f'<div class="card">{inner}'
                          f'<button type="submit" style="margin-top:1rem">Save marks &amp; re-rank</button>'
                          f'</div></form>')
        else:
            marks_form = f'<div class="card">{inner}</div>'
    else:
        marks_form = '<div class="card muted">No entries yet.</div>'

    # Add-entry form
    add = ""
    if setup:
        if me["kind"] == "relay":
            sopts = "".join(f'<option value="{s["id"]}">{escape(s["name"])}</option>' for s in schools)
            add = f"""
<div class="card"><h2>Add relay squad</h2>
<form method="post" action="/meet-events/{meid}/entries" class="row">
  <div><label>School</label><select name="school_id">{sopts}</select></div>
  <div style="max-width:90px"><label>Squad</label><input name="relay_label" value="A"></div>
  <div><label>Members (comma-sep)</label><input name="members" placeholder="Lee, Cho, Ray, Doe"></div>
  <div style="max-width:110px"><label>Seed</label><input name="seed" placeholder="mm:ss.t"></div>
  <div style="display:flex;align-items:flex-end"><button type="submit">Add</button></div>
</form></div>"""
        else:
            aopt_list = []
            for a in athletes:
                bibtxt = f' (bib {a["bib"]})' if a["bib"] else ""
                aopt_list.append(
                    f'<option value="{a["id"]}">{escape(a["name"])} — {escape(a["sname"])}{bibtxt}</option>')
            aopts = "".join(aopt_list)
            seedph = "mm:ss.t / s.t" if me["unit"] == "seconds" else "meters"
            add = f"""
<div class="card"><h2>Add athlete</h2>
<form method="post" action="/meet-events/{meid}/entries" class="row">
  <div><label>Athlete ({div})</label><select name="runner_id">{aopts or '<option disabled>No eligible athletes</option>'}</select></div>
  <div style="max-width:130px"><label>Seed</label><input name="seed" placeholder="{seedph}"></div>
  <div style="display:flex;align-items:flex-end"><button type="submit">Add</button></div>
</form></div>"""

    # Seeding + heat sheet + scan controls
    tools = ""
    if setup:
        tools = f"""
<div class="card"><h2>Seed &amp; sheets</h2>
<div class="row">
  <form class="inline" method="post" action="/meet-events/{meid}/seed">
    <input type="hidden" name="mode" value="seeded"><button type="submit">Seed by mark</button></form>
  <form class="inline" method="post" action="/meet-events/{meid}/seed">
    <input type="hidden" name="mode" value="random"><button class="ghost" type="submit">Random draw</button></form>
  <a class="btn ghost" href="/meet-events/{meid}/heatsheet.pdf">Heat sheet (PDF)</a>
</div>
<div style="margin-top:1rem"><label>AI scan-back: photograph a filled heat sheet</label>
  <input type="file" id="scanf" accept="image/*">
  <button type="button" onclick="scan()" style="margin-top:.5rem">Read marks</button>
  <div id="scanout"></div>
</div>
</div>
<script>
async function scan(){{
  const f=document.getElementById('scanf').files[0];
  if(!f){{alert('Choose a photo');return;}}
  document.getElementById('scanout').innerHTML='<p class="muted">Reading…</p>';
  const fd=new FormData(); fd.append('image',f);
  const r=await fetch('/meet-events/{meid}/scan',{{method:'POST',body:fd}});
  const j=await r.json();
  if(!r.ok){{document.getElementById('scanout').innerHTML='<p class="msg err">'+esc(j.error||'Failed')+'</p>';return;}}
  let h='<table><tr><th>Bib</th><th>Name</th><th>Mark (read)</th></tr>';
  for(const m of j.marks) h+='<tr><td>'+esc(m.bib??'')+'</td><td>'+esc(m.name??'')+'</td><td><b>'+esc(m.mark??'')+'</b></td></tr>';
  h+='</table><p class="muted">Review, then type these into the marks grid above and Save.</p>';
  document.getElementById('scanout').innerHTML=h;
}}
</script>"""

    body = (f'<p class="muted"><a href="/meets/{me["meet_id"]}/events">← Events</a></p>'
            f'<h1>{escape(ename)}</h1>{err}{marks_form}{add}{tools}')
    return shell(g.principal, body, active="meets")


# ------------------------------- vision scan-back -------------------------------
@bp.post("/meet-events/<int:meid>/scan")
@login_required
def scan_back(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_record_meet(m):
        abort(403)
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image"), 400
    media = f.mimetype or "image/jpeg"
    try:
        marks = ai.vision_read_marks(f.read(), media_type=media)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Vision read failed: {e}"), 400
    return jsonify(marks=marks)


# ------------------------------- heat sheet PDF -------------------------------
@bp.get("/meet-events/<int:meid>/heatsheet.pdf")
@login_required
def heatsheet_pdf(meid):
    me = load_meet_event(meid)
    m = load_meet(me["meet_id"])
    if not can_view_meet(m):
        abort(403)
    conn = db.connect()
    entries = conn.execute(
        "SELECT * FROM entries WHERE meet_event_id=? ORDER BY heat, lane, id", (meid,)).fetchall()
    rows = []
    for e in entries:
        name, bib, school = _entry_label(conn, e)
        rows.append({"heat": e["heat"], "lane": e["lane"], "bib": bib,
                     "name": name, "school": school})
    conn.close()
    div = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open")
    title = f'{m["name"]} — {me["ename"]} ({div})'
    pdf = pdfs.heat_sheet_pdf(title, rows, laned=bool(me["laned"]))
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="heatsheet.pdf"'})


# ------------------------------- results + scoring -------------------------------
def build_results(mid):
    """Per-event results + team point totals for a track meet."""
    ind_pts, rel_pts = points_tables()
    conn = db.connect()
    meet_events = conn.execute(
        "SELECT me.*, e.name AS ename, e.kind, e.unit, e.scoring_order, e.sort "
        "FROM meet_events me JOIN events e ON e.id=me.event_id WHERE me.meet_id=? "
        "ORDER BY e.sort, me.gender", (mid,)).fetchall()
    events_out = []
    team_pts = {}  # (school, gender) -> points
    for me in meet_events:
        table = rel_pts if me["kind"] == "relay" else ind_pts
        rows = conn.execute(
            "SELECT r.*, en.school_id FROM results r JOIN entries en ON en.id=r.entry_id "
            "WHERE en.meet_event_id=? AND r.place IS NOT NULL ORDER BY r.place", (me["id"],)).fetchall()
        items = []
        for r in rows:
            pts = table[r["place"] - 1] if r["place"] - 1 < len(table) else 0
            mark = fmt_time(r["mark_seconds"]) if me["unit"] == "seconds" else fmt_metric(r["mark_metric"])
            items.append({"place": r["place"], "mark": mark, "name": r["snap_name"],
                          "school": r["snap_school"], "points": pts})
            if r["snap_school"]:
                key = (r["snap_school"], me["gender"] or "U")
                team_pts[key] = team_pts.get(key, 0) + pts
        div = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open")
        events_out.append({"name": f'{me["ename"]} — {div}', "items": items})
    conn.close()
    # Team totals by gender
    totals = {"M": {}, "F": {}, "U": {}}
    for (school, gender), pts in team_pts.items():
        totals.setdefault(gender, {})
        totals[gender][school] = totals[gender].get(school, 0) + pts
    return {"events": events_out, "totals": totals}


def results_inner(mid, name_mode=None):
    data = build_results(mid)
    if not data["events"]:
        return '<div class="card muted">No events yet.</div>'
    html = []
    # Team scores first
    for key, label in (("M", "Boys"), ("F", "Girls"), ("U", "Open")):
        t = data["totals"].get(key) or {}
        if not t:
            continue
        ranked = sorted(t.items(), key=lambda x: -x[1])
        trs = "".join(f'<tr><td>{i+1}</td><td>{escape(s)}</td><td><b>{p}</b></td></tr>'
                      for i, (s, p) in enumerate(ranked))
        html.append(f'<div class="card"><h2>{label} — Team scores</h2>'
                    f'<table><tr><th>Rank</th><th>School</th><th>Points</th></tr>{trs}</table></div>')
    # Per-event
    for ev in data["events"]:
        if not ev["items"]:
            continue
        trs = "".join(
            f'<tr><td>{i["place"]}</td><td>{escape(demo.display(i["name"] or "", name_mode))}</td>'
            f'<td>{escape(i["school"] or "")}</td><td>{escape(i["mark"])}</td>'
            f'<td>{i["points"] or ""}</td></tr>' for i in ev["items"])
        html.append(f'<div class="card"><h2>{escape(ev["name"])}</h2>'
                    f'<table><tr><th>Pl</th><th>Competitor</th><th>School</th>'
                    f'<th>Mark</th><th>Pts</th></tr>{trs}</table></div>')
    return "".join(html)


@bp.get("/meets/<int:mid>/track-results")
@login_required
def results_page(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    body = (f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
            f'<h1>{escape(m["name"])} — Results</h1>'
            f'<div class="row"><a class="btn ghost" href="/r/{m["public_token"]}" target="_blank">'
            f'Public page ↗</a></div>{results_inner(mid, name_mode=demo.mode_for(g.principal))}')
    return shell(g.principal, body, active="meets")
