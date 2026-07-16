"""Community road-race world: Organizers (a tenant separate from school districts),
their race-director logins, and Events. An event is a `meets` row owned by an
organizer (district_id NULL, sport='road') — so it reuses the whole timing/results
engine, minus schools, rosters, and PII.
"""
import csv
import io
import re
import secrets

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort

from . import db
from .auth import login_required, role_required, create_user, send_setup_email
from .meets import load_meet, can_view_meet, can_setup_meet
from .xc import _is_org, _match_event
from .ui import shell

bp = Blueprint("road", __name__)


def _next_bib(conn, mid):
    row = conn.execute("SELECT COALESCE(MAX(bib),0) FROM participants WHERE meet_id=?", (mid,)).fetchone()
    return (row[0] or 0) + 1


def _norm_gender(v):
    v = (str(v or "").strip().upper())
    return v[0] if v[:1] in ("M", "F") else None


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "org"


def _organizer(oid):
    conn = db.connect()
    o = conn.execute("SELECT * FROM organizers WHERE id=?", (oid,)).fetchone()
    conn.close()
    return o


def _resolve_org():
    """The organizer the current principal is acting in, or None."""
    p = g.principal
    if getattr(p, "is_race_director", False):
        return p.organizer_id
    if p.is_super:
        raw = request.args.get("org") or request.form.get("org")
        return int(raw) if raw and raw.isdigit() else None
    return None


# ------------------------------- Organizers (super admin) -------------------------------
@bp.get("/organizers")
@role_required("super_admin")
def list_organizers():
    conn = db.connect()
    orgs = conn.execute("SELECT * FROM organizers ORDER BY name").fetchall()
    dirs = conn.execute(
        "SELECT id, email, name, role, organizer_id, setup_token FROM users "
        "WHERE role='race_director' ORDER BY email").fetchall()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT organizer_id, COUNT(*) FROM meets WHERE organizer_id IS NOT NULL "
        "GROUP BY organizer_id").fetchall()}
    conn.close()
    dir_by_org = {}
    for u in dirs:
        dir_by_org.setdefault(u["organizer_id"], []).append(u)

    cards = []
    for o in orgs:
        dl = "".join(
            f'<li>{escape(u["name"] or u["email"])} '
            f'<span class="muted">{escape(u["email"])}'
            f'{" · invite pending" if u["setup_token"] else ""}</span></li>'
            for u in dir_by_org.get(o["id"], [])) or '<li class="muted">No race directors yet.</li>'
        cards.append(
            f'<div class="card"><div style="display:flex;justify-content:space-between;'
            f'align-items:center;flex-wrap:wrap;gap:.5rem">'
            f'<h2 style="margin:0">🏁 {escape(o["name"])}</h2>'
            f'<a class="btn ghost" href="/events?org={o["id"]}">Events '
            f'({counts.get(o["id"], 0)}) →</a></div>'
            f'<h3 style="margin:.8rem 0 .3rem">Race directors</h3><ul style="margin:.2rem 0">{dl}</ul>'
            f'<form method="post" action="/organizers/{o["id"]}/directors" class="row" '
            f'style="gap:.5rem;flex-wrap:wrap;margin-top:.4rem">'
            f'<div><label>Director email</label><input name="email" type="email" required></div>'
            f'<div><label>Name</label><input name="name"></div>'
            f'<div style="display:flex;align-items:flex-end">'
            f'<button type="submit">+ Add race director</button></div></form></div>')

    body = (
        '<h1>Organizers</h1>'
        '<p class="muted">Community race organizers. Each runs its own road events '
        '(5K, 10K, half) with participants who register directly — no schools or rosters.</p>'
        '<div class="card"><h2>New organizer</h2>'
        '<form method="post" action="/organizers" class="row" style="gap:.6rem">'
        '<div><label>Name</label><input name="name" placeholder="e.g. Bear Lake Events" required></div>'
        '<div style="display:flex;align-items:flex-end"><button type="submit">Create</button></div>'
        '</form></div>'
        + ("".join(cards) or '<div class="card muted">No organizers yet.</div>'))
    return shell(g.principal, body, active="organizers")


@bp.post("/organizers")
@role_required("super_admin")
def create_organizer():
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    conn = db.connect()
    slug, base, n = _slugify(name), _slugify(name), 2
    while conn.execute("SELECT 1 FROM organizers WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    conn.execute("INSERT INTO organizers (name, slug) VALUES (?,?)", (name, slug))
    conn.commit()
    conn.close()
    return redirect("/organizers")


@bp.post("/organizers/<int:oid>/directors")
@role_required("super_admin")
def add_director(oid):
    if not _organizer(oid):
        abort(404)
    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("name") or "").strip() or None
    if "@" not in email:
        abort(400)
    try:
        _uid, token = create_user(email, "race_director", organizer_id=oid, name=name)
    except Exception:  # duplicate email etc.
        return redirect("/organizers")
    send_setup_email(email, token)
    return redirect("/organizers")


# ------------------------------- Events -------------------------------
@bp.get("/events")
@role_required("super_admin", "race_director")
def list_events():
    p = g.principal
    oid = _resolve_org()
    conn = db.connect()
    # Super with no organizer chosen: show a picker.
    if oid is None and p.is_super:
        orgs = conn.execute("SELECT * FROM organizers ORDER BY name").fetchall()
        conn.close()
        picks = "".join(f'<li><a href="/events?org={o["id"]}">{escape(o["name"])}</a></li>'
                        for o in orgs) or '<li class="muted">No organizers yet.</li>'
        body = ('<h1>Events</h1><p class="muted">Pick an organizer to manage its events '
                '(<a href="/organizers">manage organizers</a>).</p>'
                f'<div class="card"><ul>{picks}</ul></div>')
        return shell(p, body, active="events")
    org = conn.execute("SELECT * FROM organizers WHERE id=?", (oid,)).fetchone()
    if not org:
        conn.close()
        abort(404)
    rows = conn.execute(
        "SELECT * FROM meets WHERE organizer_id=? ORDER BY date DESC, name", (oid,)).fetchall()
    conn.close()

    trs = "".join(
        f'<tr><td><b><a href="/meets/{m["id"]}">{escape(m["name"])}</a></b></td>'
        f'<td>{escape(m["date"] or "")}</td></tr>' for m in rows)
    table = (f'<div class="card"><table><tr><th>Event</th><th>Date</th></tr>{trs}</table></div>'
             if rows else '<div class="card muted">No events yet — create one below.</div>')
    org_field = f'<input type="hidden" name="org" value="{oid}">' if p.is_super else ""
    body = (
        f'<h1>{escape(org["name"])} — Events</h1>'
        + ('<p class="muted"><a href="/organizers">← Organizers</a></p>' if p.is_super else '')
        + table
        + '<div class="card"><h2>New event</h2>'
        + f'<form method="post" action="/events" class="row" style="gap:.6rem">{org_field}'
        + '<div><label>Name</label><input name="name" placeholder="e.g. Summer Classic" required></div>'
        + '<div style="max-width:180px"><label>Date</label><input name="date" type="date"></div>'
        + '<div style="display:flex;align-items:flex-end"><button type="submit">Create event</button>'
        + '</div></form></div>')
    return shell(p, body, active="events")


@bp.post("/events")
@role_required("super_admin", "race_director")
def create_event():
    oid = _resolve_org()
    if oid is None or not _organizer(oid):
        abort(400)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    date = (request.form.get("date") or "").strip() or None
    conn = db.connect()
    mid = conn.execute(
        "INSERT INTO meets (organizer_id, sport, name, date, public_token, team_scoring) "
        "VALUES (?,?,?,?,?,0)",
        (oid, "road", name, date, secrets.token_urlsafe(8))).lastrowid
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


# ------------------------------- Participants -------------------------------
def _event_or_403(mid, guard=can_view_meet):
    m = load_meet(mid)
    if not guard(m) or not _is_org(m):
        abort(403)
    return m


@bp.get("/meets/<int:mid>/participants")
@login_required
def participants(mid):
    m = _event_or_403(mid)
    editable = can_setup_meet(m)
    conn = db.connect()
    races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (mid,)).fetchall()
    ps = conn.execute("SELECT * FROM participants WHERE meet_id=? ORDER BY name", (mid,)).fetchall()
    conn.close()
    rname = {r["id"]: r["name"] for r in races}
    by_race = {}
    for p in ps:
        by_race.setdefault(p["race_id"], []).append(p)

    def prow(p):
        bits = []
        if p["age"] is not None:
            bits.append(f'age {p["age"]}')
        if p["gender"]:
            bits.append(p["gender"])
        if p["club"]:
            bits.append(escape(p["club"]))
        if p["city"]:
            bits.append(escape(p["city"]))
        meta = " · ".join(str(b) for b in bits)
        rm = (f'<form class="inline" method="post" action="/participants/{p["id"]}/delete" '
              f'onsubmit="return confirm(\'Remove {escape(p["name"])}?\')">'
              f'<button class="ic del">✕</button></form>') if editable else ""
        bib = f'<b>#{p["bib"]}</b>' if p["bib"] is not None else '<span class="muted">no bib</span>'
        return (f'<div class="arow" data-name="{escape((p["name"] or "").lower())}">'
                f'<span>{bib} &nbsp; {escape(p["name"])} <span class="muted">{meta}</span></span>'
                f'<span>{rm}</span></div>')

    sections = []
    order = [r["id"] for r in races] + [None]
    for rid in order:
        plist = by_race.get(rid, [])
        if rid is None and not plist:
            continue
        label = rname.get(rid, "Unassigned distance")
        rows = "".join(prow(p) for p in plist) or '<p class="muted">None yet.</p>'
        sections.append(
            f'<div class="card"><h3 style="margin:.1rem 0 .5rem">{escape(label)} '
            f'<span class="muted">— {len(plist)}</span></h3>{rows}</div>')

    dist_opts = "".join(f'<option value="{r["id"]}">{escape(r["name"])}</option>' for r in races)
    tools = ""
    if editable:
        if races:
            tools = (
                '<div class="card"><h2>Import registrations (CSV)</h2>'
                '<p class="muted" style="margin-top:0">Columns (any order): '
                '<code>bib, name, age, gender, distance, city, club</code>. '
                'A blank bib auto-numbers. Distance is matched to your events by name '
                '(e.g. “5K” → “5K Run”).</p>'
                f'<form method="post" action="/meets/{mid}/participants/import" '
                'enctype="multipart/form-data">'
                '<input type="file" name="file" accept=".csv,text/csv"><br>'
                '<p class="muted" style="margin:.5rem 0 .2rem">…or paste CSV:</p>'
                '<textarea name="csv" rows="4" style="width:100%" '
                'placeholder="bib,name,age,gender,distance,city,club&#10;101,Jane Doe,34,F,10K,Provo,Runners"></textarea>'
                '<button type="submit" style="margin-top:.5rem">Import</button></form></div>'
                '<div class="card"><h2>Add one</h2>'
                f'<form method="post" action="/meets/{mid}/participants" class="row" style="gap:.5rem;flex-wrap:wrap">'
                '<div style="max-width:90px"><label>Bib</label><input name="bib" type="number" placeholder="auto"></div>'
                '<div><label>Name</label><input name="name" required></div>'
                '<div style="max-width:80px"><label>Age</label><input name="age" type="number"></div>'
                '<div style="max-width:90px"><label>Sex</label>'
                '<select name="gender"><option value="">—</option><option>M</option><option>F</option></select></div>'
                f'<div style="max-width:160px"><label>Distance</label><select name="race_id">{dist_opts}</select></div>'
                '<div style="max-width:130px"><label>City</label><input name="city"></div>'
                '<div style="max-width:150px"><label>Club/Team</label><input name="club"></div>'
                '<div style="display:flex;align-items:flex-end"><button type="submit">Add</button></div>'
                '</form></div>')
        else:
            tools = ('<div class="card muted">Add at least one distance on the '
                     f'<a href="/meets/{mid}">Setup</a> tab before adding participants.</div>')

    msg = request.args.get("msg", "")
    msg_html = f'<div class="card" style="border-color:var(--ok)">{escape(msg)}</div>' if msg else ""
    body = (
        f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
        f'<h1>{escape(m["name"])} — Participants</h1>'
        f'{_road_tabs(mid, "participants")}'
        '<style>.arow{display:flex;justify-content:space-between;align-items:center;gap:.6rem;'
        'padding:.3rem .1rem;border-bottom:1px solid var(--line)}.arow:last-child{border-bottom:0}</style>'
        f'{msg_html}'
        f'<input id="psearch" placeholder="Search name…" oninput="pfilt()" style="width:100%;margin:.2rem 0 1rem">'
        f'{"".join(sections) or "<div class=card muted>No participants yet.</div>"}'
        f'{tools}'
        '<script>function pfilt(){var q=document.getElementById("psearch").value.toLowerCase();'
        'document.querySelectorAll(".arow").forEach(function(r){'
        'r.style.display=(!q||(r.getAttribute("data-name")||"").indexOf(q)>=0)?"":"none";});}</script>')
    return shell(g.principal, body, active="events")


def _road_tabs(mid, active):
    from .xc import _xc_tabs
    return _xc_tabs(mid, active, road=True, organizer=True)


@bp.post("/meets/<int:mid>/participants")
@login_required
def add_participant(mid):
    m = _event_or_403(mid, can_setup_meet)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    age = (request.form.get("age") or "").strip()
    age = int(age) if age.isdigit() else None
    gender = _norm_gender(request.form.get("gender"))
    city = (request.form.get("city") or "").strip() or None
    club = (request.form.get("club") or "").strip() or None
    rid_raw = (request.form.get("race_id") or "").strip()
    race_id = int(rid_raw) if rid_raw.isdigit() else None
    conn = db.connect()
    if race_id is not None and not conn.execute(
            "SELECT 1 FROM races WHERE id=? AND meet_id=?", (race_id, mid)).fetchone():
        conn.close(); abort(400)
    bib_raw = (request.form.get("bib") or "").strip()
    bib = int(bib_raw) if bib_raw.isdigit() else _next_bib(conn, mid)
    try:
        conn.execute(
            "INSERT INTO participants (meet_id, race_id, bib, name, age, gender, city, club) "
            "VALUES (?,?,?,?,?,?,?,?)", (mid, race_id, bib, name, age, gender, city, club))
        conn.commit()
    except Exception:  # duplicate bib in this meet
        conn.close()
        return redirect(f"/meets/{mid}/participants?msg=Bib+{bib}+is+already+used")
    conn.close()
    return redirect(f"/meets/{mid}/participants")


def _pick(rowmap, *names):
    for n in names:
        if n in rowmap and str(rowmap[n]).strip():
            return str(rowmap[n]).strip()
    return ""


@bp.post("/meets/<int:mid>/participants/import")
@login_required
def import_participants(mid):
    m = _event_or_403(mid, can_setup_meet)
    text = ""
    f = request.files.get("file")
    if f and f.filename:
        text = f.read().decode("utf-8-sig", "replace")
    if not text.strip():
        text = request.form.get("csv") or ""
    text = text.strip()
    if not text:
        return redirect(f"/meets/{mid}/participants?msg=Nothing+to+import")

    conn = db.connect()
    races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (mid,)).fetchall()
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any((c or "").strip() for c in r)]
    if not rows:
        conn.close()
        return redirect(f"/meets/{mid}/participants?msg=Nothing+to+import")
    header = [h.strip().lower() for h in rows[0]]
    added = skipped = unmatched = 0
    nextbib = _next_bib(conn, mid)
    for r in rows[1:]:
        rowmap = {header[i]: (r[i] if i < len(r) else "") for i in range(len(header))}
        name = _pick(rowmap, "name", "athlete", "runner")
        if not name:
            fn, ln = _pick(rowmap, "first", "first name", "firstname"), _pick(rowmap, "last", "last name", "lastname")
            name = (fn + " " + ln).strip()
        if not name:
            skipped += 1
            continue
        bib_s = _pick(rowmap, "bib", "bib number", "number", "bib #")
        bib = int(bib_s) if bib_s.isdigit() else nextbib
        if not bib_s.isdigit():
            nextbib += 1
        age_s = _pick(rowmap, "age")
        age = int(age_s) if age_s.isdigit() else None
        gender = _norm_gender(_pick(rowmap, "gender", "sex", "m/f"))
        dist = _pick(rowmap, "distance", "event", "race")
        race_id = _match_event(dist, races) if dist else None
        if dist and race_id is None:
            unmatched += 1
        city = _pick(rowmap, "city", "town") or None
        club = _pick(rowmap, "club", "team") or None
        try:
            conn.execute(
                "INSERT INTO participants (meet_id, race_id, bib, name, age, gender, city, club) "
                "VALUES (?,?,?,?,?,?,?,?)", (mid, race_id, bib, name, age, gender, city, club))
            added += 1
        except Exception:  # duplicate bib
            skipped += 1
    conn.commit()
    conn.close()
    msg = f"Imported {added}."
    if skipped:
        msg += f" Skipped {skipped} (missing name or duplicate bib)."
    if unmatched:
        msg += f" {unmatched} had a distance that didn't match an event (left unassigned)."
    return redirect(f"/meets/{mid}/participants?msg={msg.replace(' ', '+')}")


@bp.post("/participants/<int:pid>/delete")
@login_required
def delete_participant(pid):
    conn = db.connect()
    p = conn.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        abort(404)
    _event_or_403(p["meet_id"], can_setup_meet)
    conn = db.connect()
    conn.execute("DELETE FROM participants WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{p['meet_id']}/participants")
