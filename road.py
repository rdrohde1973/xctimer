"""Community road-race world: Organizers (a tenant separate from school districts),
their race-director logins, and Events. An event is a `meets` row owned by an
organizer (district_id NULL, sport='road') — so it reuses the whole timing/results
engine, minus schools, rosters, and PII.
"""
import csv
import io
import json
import logging
import os
import re
import secrets
from datetime import timedelta

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, Response, make_response, jsonify

from . import db
from .auth import login_required, role_required, create_user, send_setup_email
from .meets import load_meet, can_view_meet, can_setup_meet, _purge_meet
from .xc import _is_org, _match_event
from .ui import shell, CSRF_JS, BRAND_HTML, HEAD_EXTRA

HOST_FEE_CENTS = int(os.environ.get("XC_HOST_FEE_CENTS", "5000"))   # self-serve event fee ($50)

bp = Blueprint("road", __name__)


def _load_settings(mid):
    conn = db.connect()
    row = conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    try:
        return json.loads((row["settings_json"] if row else None) or "{}")
    except (ValueError, TypeError):
        return {}


def _save_settings(mid, s):
    conn = db.connect()
    conn.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps(s), mid))
    conn.commit()
    conn.close()


def _reg_base():
    return os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))


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
            f'<div style="display:flex;gap:.4rem;align-items:center">'
            f'<a class="btn ghost" href="/events?org={o["id"]}">Events '
            f'({counts.get(o["id"], 0)}) →</a>'
            f'<form class="inline" method="post" action="/organizers/{o["id"]}/delete" '
            f'onsubmit="return confirm(\'Delete organizer “{escape(o["name"])}” and its '
            f'{counts.get(o["id"], 0)} event(s), all its race directors, participants, and '
            f'results? This cannot be undone.\')">'
            f'<button class="danger" title="Delete organizer">✕ Delete</button></form>'
            f'</div></div>'
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


@bp.post("/organizers/<int:oid>/delete")
@role_required("super_admin")
def delete_organizer(oid):
    if not _organizer(oid):
        abort(404)
    conn = db.connect()
    # Cascade every event this organizer owns (participants, races, results, …).
    mids = [r[0] for r in conn.execute(
        "SELECT id FROM meets WHERE organizer_id=?", (oid,)).fetchall()]
    for mid in mids:
        _purge_meet(conn, mid)
    # Remove the organizer's race-director logins and their active sessions.
    dir_ids = [r[0] for r in conn.execute(
        "SELECT id FROM users WHERE role='race_director' AND organizer_id=?", (oid,)).fetchall()]
    for uid in dir_ids:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE role='race_director' AND organizer_id=?", (oid,))
    conn.execute("DELETE FROM organizers WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return redirect("/organizers")


# ------------------------------- Events -------------------------------
@bp.get("/events")
@role_required("super_admin", "race_director")
def list_events():
    p = g.principal
    if getattr(p, "owns_meet", None) is not None:   # self-serve owner: only their one event
        return redirect(f"/meets/{p.owns_meet}")
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
        f'<td>{escape(m["date"] or "")}</td>'
        f'<td style="text-align:right"><form class="inline" method="post" '
        f'action="/meets/{m["id"]}/delete" onsubmit="return confirm('
        f'\'Delete “{escape(m["name"])}” and ALL its participants, bibs, and results? '
        f'This cannot be undone.\')">'
        f'<button class="danger" style="padding:.2rem .5rem;line-height:1" title="Delete event">✕</button>'
        f'</form></td></tr>' for m in rows)
    table = (f'<div class="card"><table><tr><th>Event</th><th>Date</th><th></th></tr>{trs}</table></div>'
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
    if getattr(g.principal, "owns_meet", None) is not None:   # owners get exactly one event
        abort(403)
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
    # Start with one race so the event works end-to-end immediately (registration needs
    # a race to enter). Guess a distance from the name (e.g. "…5K"), else a generic name.
    km = re.search(r"\b(\d+)\s?[kK]\b", name)
    if km:
        race_name = km.group(1) + "K"
    elif re.search(r"half\s?marathon", name, re.IGNORECASE):
        race_name = "Half Marathon"
    elif re.search(r"\bmarathon\b", name, re.IGNORECASE):
        race_name = "Marathon"
    elif re.search(r"fun\s?run", name, re.IGNORECASE):
        race_name = "Fun Run"
    else:
        race_name = "Race 1"
    # Unified capture: tap -> scan or select (fill open slots by camera scan or the picker).
    conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)",
                 (mid, race_name, "tapselect"))
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

    def race_select(p):
        opts = ""
        for r in races:
            sel = " selected" if r["id"] == p["race_id"] else ""
            opts += f'<option value="{r["id"]}"{sel}>{escape(r["name"])}</option>'
        opts += f'<option value=""{" selected" if p["race_id"] is None else ""}>— unassigned —</option>'
        return (f'<form class="inline" method="post" action="/participants/{p["id"]}/race">'
                f'<select name="race_id" onchange="this.form.submit()" '
                f'style="padding:.2rem .3rem;font-size:.85rem">{opts}</select></form>')

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
        move = race_select(p) if (editable and len(races) > 1) else ""
        bib = f'<b>#{p["bib"]}</b>' if p["bib"] is not None else '<span class="muted">no bib</span>'
        return (f'<div class="arow" data-name="{escape((p["name"] or "").lower())}">'
                f'<span>{bib} &nbsp; {escape(p["name"])} <span class="muted">{meta}</span></span>'
                f'<span style="display:flex;gap:.4rem;align-items:center">{move}{rm}</span></div>')

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
                '<code>bib, name, age, gender, race, city, club</code>. '
                'A blank bib auto-numbers; a bib that already exists updates that runner '
                '(re-import a corrected file anytime). The race column is matched to your '
                'races by name (e.g. “5K” → “5K Run”).</p>'
                f'<form method="post" action="/meets/{mid}/participants/import" '
                'enctype="multipart/form-data">'
                '<input type="file" name="file" accept=".csv,text/csv"><br>'
                '<p class="muted" style="margin:.5rem 0 .2rem">…or paste CSV:</p>'
                '<textarea name="csv" rows="4" style="width:100%" '
                'placeholder="bib,name,age,gender,race,city,club&#10;101,Jane Doe,34,F,10K,Provo,Runners"></textarea>'
                '<button type="submit" style="margin-top:.5rem">Import</button></form></div>'
                '<div class="card"><h2>Add one</h2>'
                f'<form method="post" action="/meets/{mid}/participants" class="row" style="gap:.5rem;flex-wrap:wrap">'
                '<div style="max-width:90px"><label>Bib</label><input name="bib" type="number" placeholder="auto"></div>'
                '<div><label>Name</label><input name="name" required></div>'
                '<div style="max-width:80px"><label>Age</label><input name="age" type="number"></div>'
                '<div style="max-width:90px"><label>Sex</label>'
                '<select name="gender"><option value="">—</option><option>M</option><option>F</option></select></div>'
                f'<div style="max-width:160px"><label>Race</label><select name="race_id">{dist_opts}</select></div>'
                '<div style="max-width:130px"><label>City</label><input name="city"></div>'
                '<div style="max-width:150px"><label>Club/Team</label><input name="club"></div>'
                '<div style="display:flex;align-items:flex-end"><button type="submit">Add</button></div>'
                '</form></div>')
        else:
            tools = ('<div class="card muted">Add at least one race on the '
                     f'<a href="/meets/{mid}">Setup</a> tab before adding participants.</div>')

    msg = request.args.get("msg", "")
    msg_html = f'<div class="card" style="border-color:var(--ok)">{escape(msg)}</div>' if msg else ""
    from .meets import road_sticker_controls
    ss = is_web_event(m)
    tag_note = ('Camera-readable ArUco tags — event logo + number + name, one per runner. '
                if ss else 'Event logo + number + name, one per runner. ')
    print_bar = (
        f'<div class="card" style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap">'
        f'<b>🏁 Print bibs</b> {road_sticker_controls(mid, self_serve=ss)} '
        f'<span class="muted">{tag_note}Use Avery 5163 (2"×4") sticker sheets.</span></div>')
    body = (
        f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
        f'<h1>{escape(m["name"])} — Participants</h1>'
        f'{_road_tabs(mid, "participants")}'
        '<style>.arow{display:flex;justify-content:space-between;align-items:center;gap:.6rem;'
        'padding:.3rem .1rem;border-bottom:1px solid var(--line)}.arow:last-child{border-bottom:0}</style>'
        f'{msg_html}'
        f'{print_bar}'
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
    added = updated = skipped = unmatched = 0
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
        provided = bib_s.isdigit()
        bib = int(bib_s) if provided else nextbib
        if not provided:
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

        # Upsert by bib: a bib already in this event UPDATES that participant, filling
        # only the fields the CSV actually provides (a sparse row won't wipe good data).
        existing = conn.execute("SELECT * FROM participants WHERE meet_id=? AND bib=?",
                                (mid, bib)).fetchone() if provided else None
        if existing:
            conn.execute(
                "UPDATE participants SET name=?, age=?, gender=?, race_id=?, city=?, club=? WHERE id=?",
                (name,
                 age if age is not None else existing["age"],
                 gender if gender else existing["gender"],
                 race_id if (dist and race_id is not None) else existing["race_id"],
                 city if city else existing["city"],
                 club if club else existing["club"],
                 existing["id"]))
            updated += 1
        else:
            try:
                conn.execute(
                    "INSERT INTO participants (meet_id, race_id, bib, name, age, gender, city, club) "
                    "VALUES (?,?,?,?,?,?,?,?)", (mid, race_id, bib, name, age, gender, city, club))
                added += 1
            except Exception:  # rare bib race
                skipped += 1
    conn.commit()
    conn.close()
    msg = f"Imported {added} new"
    if updated:
        msg += f", updated {updated} existing"
    msg += "."
    if skipped:
        msg += f" Skipped {skipped} (missing name)."
    if unmatched:
        msg += f" {unmatched} had a race that didn't match (left unassigned)."
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


@bp.post("/participants/<int:pid>/race")
@login_required
def participant_race(pid):
    """Move a runner to a different race (inline dropdown on the Participants tab)."""
    conn = db.connect()
    p = conn.execute("SELECT * FROM participants WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not p:
        abort(404)
    _event_or_403(p["meet_id"], can_setup_meet)
    rid_raw = (request.form.get("race_id") or "").strip()
    race_id = int(rid_raw) if rid_raw.isdigit() else None
    conn = db.connect()
    if race_id is not None and not conn.execute(
            "SELECT 1 FROM races WHERE id=? AND meet_id=?", (race_id, p["meet_id"])).fetchone():
        conn.close(); abort(400)
    conn.execute("UPDATE participants SET race_id=? WHERE id=?", (race_id, pid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{p['meet_id']}/participants")


# ------------------------------- event branding + registration settings -------------------------------
def _logo_bg(url):
    """Sample a logo's background colour (corner/edge pixels) -> '#rrggbb', or None
    when the logo is transparent (so the page keeps its default background)."""
    if not url:
        return None
    try:
        from collections import Counter
        from PIL import Image
        path = os.path.join(os.path.dirname(__file__), "static", "logos", os.path.basename(url))
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        pts = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1)]
        cols = []
        for x, y in pts:
            r, g, b, a = im.getpixel((x, y))
            if a < 200:
                continue                       # transparent edge -> ignore
            cols.append((r // 8 * 8, g // 8 * 8, b // 8 * 8))   # quantize to fight JPEG noise
        if not cols:
            return None
        r, g, b = Counter(cols).most_common(1)[0][0]
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:  # noqa: BLE001 — never block a logo upload on colour sampling
        return None


@bp.post("/meets/<int:mid>/logo")
@login_required
def event_logo(mid):
    m = _event_or_403(mid, can_setup_meet)
    from .schools import _save_logo
    lp = _save_logo(request.files.get("logo"), f"event-{m['name']}")
    if lp:
        s = _load_settings(mid)
        s["event_logo"] = lp
        s["logo_bg"] = _logo_bg(lp)            # match the signup page to the logo
        _save_settings(mid, s)
    return redirect(f"/meets/{mid}")


@bp.post("/meets/<int:mid>/event-settings")
@login_required
def event_settings(mid):
    m = _event_or_403(mid, can_setup_meet)
    s = _load_settings(mid)
    cwo = db.connect()
    web = _web_org_id(cwo)
    cwo.commit()
    cwo.close()
    # Self-serve web events can't open registration until the $50 is paid (pay-to-go-live).
    unpaid_web = (m["organizer_id"] == web) and not s.get("host_paid")
    s["reg_open"] = bool(request.form.get("reg_open")) and not unpaid_web
    s["reg_text"] = (request.form.get("reg_text") or "").strip()
    fee = (request.form.get("fee") or "").strip()
    try:
        s["fee_cents"] = int(round(float(fee) * 100)) if fee else 0
    except ValueError:
        s["fee_cents"] = 0
    s["venmo"] = _venmo_user(request.form.get("venmo"))
    _save_settings(mid, s)
    return redirect(f"/meets/{mid}")


@bp.get("/meets/<int:mid>/participants/stickers.pdf")
@login_required
def participant_stickers(mid):
    m = _event_or_403(mid, can_view_meet)
    template = "5163"          # same Avery sheet as Track / XC
    # Self-serve events are ArUco-only (camera tap-then-scan) — never emit QR bibs for them.
    code = "aruco" if (request.args.get("code") == "aruco" or is_web_event(m)) else None
    try:
        spares = int(request.args.get("spares", "0"))
    except (TypeError, ValueError):
        spares = 0
    spares = max(0, min(spares, 200))
    s = _load_settings(mid)
    conn = db.connect()
    ps = conn.execute(
        "SELECT bib, name FROM participants WHERE meet_id=? AND bib IS NOT NULL ORDER BY bib",
        (mid,)).fetchall()
    conn.close()
    from . import pdfs
    athletes = [{"bib": p["bib"], "name": p["name"], "code": code} for p in ps]
    nextspare = max((p["bib"] for p in ps), default=0) + 1
    for _ in range(spares):    # blank stickers (number + code, no name) to hand-write walk-ups
        athletes.append({"bib": nextspare, "name": "", "code": code})
        nextspare += 1
    data = pdfs.bib_stickers_pdf(m["name"], athletes, template=template, logo_path=s.get("event_logo"))
    fname = (m["name"] or "stickers").replace(" ", "_")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}-stickers.pdf"',
                             "Cache-Control": "no-store, max-age=0"})


# ------------------------------- public self-registration -------------------------------
def _event_by_token(token):
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE public_token=?", (token,)).fetchone()
    conn.close()
    if not m or not _is_org(m):
        abort(404)
    return m


def _fee_str(cents):
    return f"${cents/100:,.2f}" if cents else ""


def _venmo_user(raw):
    """Normalize a Venmo handle: accept '@name', 'name', or a full venmo.com/[u/]name link."""
    v = (raw or "").strip()
    if not v:
        return ""
    if "venmo.com/" in v:
        v = v.split("venmo.com/", 1)[1]
    v = v.split("?", 1)[0].strip("/")
    if v.startswith("u/"):
        v = v[2:]
    return v.lstrip("@").strip("/")


def _venmo_url(user, amount_cents, note):
    """A Venmo 'pay' deep link — opens the Venmo app (mobile) prefilled to pay `user`."""
    from urllib.parse import quote
    return (f"https://venmo.com/{quote(user)}?txn=pay"
            f"&amount={amount_cents/100:.2f}&note={quote(note)}")


def _reg_shell(m, inner):
    s = _load_settings(m["id"])
    logo = s.get("event_logo")
    logo_tag = (f'<img src="{escape(logo)}" alt="" style="max-height:90px;max-width:230px;'
                f'object-fit:contain">' if logo else "")
    if logo and "logo_bg" not in s:            # backfill for logos uploaded before this feature
        s["logo_bg"] = _logo_bg(logo)
        _save_settings(m["id"], s)
    # Match the page background to the logo; flip the header text to stay readable on it.
    bg = s.get("logo_bg") or "#eef1f5"
    try:
        r, g, b = int(bg[1:3], 16), int(bg[3:5], 16), int(bg[5:7], 16)
        dark_bg = (0.299 * r + 0.587 * g + 0.114 * b) < 140
    except (ValueError, IndexError):
        dark_bg = False
    h1_col = "#ffffff" if dark_bg else "#12385f"
    sub_col = "rgba(255,255,255,.85)" if dark_bg else "#5b6b7c"
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Register · {escape(m['name'])}</title>{HEAD_EXTRA}<script>{CSRF_JS}</script>
<style>
*{{box-sizing:border-box}}
body{{margin:0;font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:{bg};color:#1b2b3a}}
main{{max-width:640px;margin:0 auto;padding:1.2rem 1rem 3rem}}
.hero{{text-align:center;padding:1.4rem 1rem .6rem}}
.hero h1{{margin:.6rem 0 .2rem;color:{h1_col}}}
.hero .sub{{color:{sub_col}}}
.card{{background:#fff;border:1px solid #d9e0e8;border-radius:14px;padding:1.1rem 1.2rem;margin:0 0 1rem}}
label{{display:block;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#5b6b7c;font-weight:700;margin:.5rem 0 .2rem}}
input,select,textarea{{width:100%;padding:.6rem;border:1px solid #cdd8e6;border-radius:9px;font-size:1rem;background:#fff;color:#1b2b3a}}
.row{{display:flex;gap:.6rem;flex-wrap:wrap}}.row>div{{flex:1;min-width:110px}}
.runner{{border:1px solid #e3e9f1;border-radius:12px;padding:.8rem;margin:.6rem 0;position:relative}}
.runner h3{{margin:.1rem 0 .3rem;color:#12385f;font-size:1rem}}
.rm{{position:absolute;top:.5rem;right:.6rem;background:none;border:0;color:#c0483f;font-weight:800;cursor:pointer;width:auto;font-size:1.1rem}}
button.primary{{background:#ea6a2d;color:#fff;border:0;font-weight:800;padding:.8rem 1.4rem;border-radius:11px;font-size:1.05rem;cursor:pointer;width:auto}}
button.add{{background:#eef3f9;border:1px dashed #9db4cf;color:#12385f;font-weight:700;padding:.6rem;border-radius:10px;cursor:pointer;width:100%}}
.fee{{background:#fff8f0;border:1px solid #f0d3b3;border-radius:10px;padding:.6rem .8rem;color:#8a5a1f;font-weight:600}}
.pubfoot{{text-align:center;color:#8a97a5;font-size:.85rem;padding:1.4rem}}
.hp{{position:absolute;left:-9999px}}
</style></head><body>
<div class="hero">{logo_tag}<h1>{escape(m['name'])}</h1>
<div class="sub">🛣 {escape(m['date'] or 'Register')}</div></div>
<main>{inner}</main>
<footer class="pubfoot">Powered by {BRAND_HTML}</footer>
</body></html>"""


@bp.get("/register/<token>")
def register(token):
    m = _event_by_token(token)
    s = _load_settings(m["id"])
    conn = db.connect()
    races = conn.execute("SELECT id, name FROM races WHERE meet_id=? ORDER BY id", (m["id"],)).fetchall()
    conn.close()
    if not s.get("reg_open"):
        return _reg_shell(m, '<div class="card">Registration for this event is not open yet. '
                             'Please check back soon.</div>'), 200
    if not races:
        return _reg_shell(m, '<div class="card">Registration will open once the organizer adds the '
                             'race(s). Please check back soon.</div>'), 200

    blurb = escape(s.get("reg_text") or "").replace("\n", "<br>")
    blurb_card = f'<div class="card">{blurb}</div>' if blurb else ""
    fee = s.get("fee_cents", 0)
    _pay = "pay by Venmo right after registering" if s.get("venmo") else "collected at packet pickup"
    fee_card = (f'<div class="card fee">Entry fee: {_fee_str(fee)} per runner — '
                f'{_pay}.</div>' if fee else "")
    race_opts = "".join(f'<option value="{r["id"]}">{escape(r["name"])}</option>' for r in races)

    def block(n, removable):
        rm = '<button type="button" class="rm" onclick="rmRunner(this)">✕</button>' if removable else ""
        return (
            f'<div class="runner">{rm}<h3>Runner <span class="rn">{n}</span></h3>'
            '<label>Full name</label><input name="rname" autocomplete="off">'
            '<div class="row"><div><label>Age (race day)</label><input name="rage" type="number" min="0" inputmode="numeric"></div>'
            '<div><label>Sex</label><select name="rgender"><option value="">—</option><option>M</option><option>F</option></select></div></div>'
            f'<label>Race</label><select name="rrace">{race_opts}</select>'
            '<div class="row"><div><label>City</label><input name="rcity"></div>'
            '<div><label>Club / Team</label><input name="rclub"></div></div></div>')

    inner = (
        blurb_card + fee_card +
        f'<form method="post" action="/register/{escape(token)}">'
        '<input type="text" name="website" class="hp" tabindex="-1" autocomplete="off" aria-hidden="true">'
        f'<div id="runners">{block(1, False)}</div>'
        '<button type="button" class="add" onclick="addRunner()">+ Add another runner</button>'
        '<div style="text-align:center;margin-top:1.2rem">'
        '<button type="submit" class="primary">Register</button></div></form>'
        f'<template id="rtmpl">{block("N", True)}</template>'
        '<script>'
        'function renum(){var i=1;document.querySelectorAll("#runners .runner .rn").forEach(function(s){s.textContent=i++;});}'
        'function addRunner(){var t=document.getElementById("rtmpl").content.cloneNode(true);'
        'document.getElementById("runners").appendChild(t);renum();}'
        'function rmRunner(b){var r=b.closest(".runner");if(document.querySelectorAll("#runners .runner").length>1)r.remove();renum();}'
        '</script>')
    return _reg_shell(m, inner)


@bp.post("/register/<token>")
def register_post(token):
    m = _event_by_token(token)
    s = _load_settings(m["id"])
    if not s.get("reg_open"):
        abort(403)
    if (request.form.get("website") or "").strip():   # honeypot -> silent no-op
        return redirect(f"/register/{token}")
    names = request.form.getlist("rname")
    ages = request.form.getlist("rage")
    genders = request.form.getlist("rgender")
    rids = request.form.getlist("rrace")
    cities = request.form.getlist("rcity")
    clubs = request.form.getlist("rclub")
    fee = s.get("fee_cents", 0)
    paid = 0 if fee else 1

    conn = db.connect()
    valid_races = {r[0] for r in conn.execute("SELECT id FROM races WHERE meet_id=?", (m["id"],)).fetchall()}
    nextbib = _next_bib(conn, m["id"])
    created = []
    # PAYMENT HOOK: when online payment is added, this loop runs only after a
    # successful charge (Stripe checkout session) and sets paid=1 on the created rows.
    for i, raw in enumerate(names[:25]):   # cap per submission
        name = (raw or "").strip()
        if not name:
            continue
        age = ages[i].strip() if i < len(ages) else ""
        age = int(age) if age.isdigit() else None
        gender = _norm_gender(genders[i] if i < len(genders) else "")
        rid = rids[i] if i < len(rids) else ""
        race_id = int(rid) if rid.isdigit() and int(rid) in valid_races else None
        city = (cities[i].strip() if i < len(cities) else "") or None
        club = (clubs[i].strip() if i < len(clubs) else "") or None
        bib = nextbib
        nextbib += 1
        try:
            conn.execute(
                "INSERT INTO participants (meet_id, race_id, bib, name, age, gender, city, club, paid) "
                "VALUES (?,?,?,?,?,?,?,?,?)", (m["id"], race_id, bib, name, age, gender, city, club, paid))
            created.append((bib, name))
        except Exception:
            nextbib -= 1
    conn.commit()
    conn.close()

    if not created:
        return _reg_shell(m, '<div class="card">Please enter at least one runner\'s name. '
                             f'<a href="/register/{escape(token)}">Back</a></div>'), 200
    rname = {r[0]: r[1] for r in db.connect().execute("SELECT id,name FROM races WHERE meet_id=?", (m["id"],)).fetchall()}
    rows = "".join(f'<li><b>Bib #{b}</b> — {escape(nm)}</li>' for b, nm in created)
    total = fee * len(created)
    venmo = s.get("venmo") or ""
    redirect_js = ""
    if fee and venmo:
        vurl = _venmo_url(venmo, total, f"{m['name']} entry")
        fee_line = (
            f'<div class="card fee">Entry fee: <b>{_fee_str(total)}</b> '
            f'({len(created)} × {_fee_str(fee)}).<br>'
            f'<a class="btn" href="{escape(vurl)}" style="display:inline-block;margin-top:.5rem;'
            f'background:#3d95ce;color:#fff;padding:.6rem 1.1rem;border-radius:9px;'
            f'text-decoration:none;font-weight:700">Pay {_fee_str(total)} with Venmo</a>'
            f'<div class="muted" style="font-size:.8rem;margin-top:.3rem">Sends you to Venmo '
            f'(@{escape(venmo)}). If it doesn\'t open automatically, tap the button.</div></div>')
        redirect_js = f'<script>setTimeout(function(){{location.href={json.dumps(vurl)};}},1800);</script>'
    elif fee:
        fee_line = (f'<div class="card fee">Amount due at packet pickup: '
                    f'{_fee_str(total)} ({len(created)} × {_fee_str(fee)}).</div>')
    else:
        fee_line = ""
    inner = (f'<div class="card"><h2 style="margin-top:0;color:#2e8b57">✅ You\'re registered!</h2>'
             f'<p>See you on race day. Your bib number(s):</p><ul>{rows}</ul></div>'
             f'{fee_line}'
             f'<div style="text-align:center"><a href="/register/{escape(token)}">'
             f'Register more runners</a></div>{redirect_js}')
    return _reg_shell(m, inner)


@bp.get("/meets/<int:mid>/participants/tags.pdf")
@login_required
def participant_tags(mid):
    """Camera-timing tag sheet: big ArUco tag per participant (prototype)."""
    m = _event_or_403(mid, can_view_meet)
    conn = db.connect()
    ps = conn.execute(
        "SELECT bib, name FROM participants WHERE meet_id=? AND bib IS NOT NULL ORDER BY bib",
        (mid,)).fetchall()
    conn.close()
    from . import pdfs
    data = pdfs.road_tag_sheet_pdf(m["name"], [dict(p) for p in ps])
    fname = (m["name"] or "tags").replace(" ", "_")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{fname}-camera-tags.pdf"',
                             "Cache-Control": "no-store, max-age=0"})


# ============================ self-serve "host your own fun run" ============================
# Strangers create a SINGLE community event under one shared "XCTimer Web" organizer, get a
# magic link scoped to just that event, pay $50 to go live (Venmo now; Square later), and the
# event auto-deletes 30 days after its date (see reap_web_events + the xctimer-reap timer).

def _web_org_id(conn):
    """The shared 'XCTimer Web' organizer for self-serve events (lazily created)."""
    row = conn.execute("SELECT id FROM organizers WHERE slug='xctimer-web'").fetchone()
    return row["id"] if row else conn.execute(
        "INSERT INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')").lastrowid


def host_paid(m):
    try:
        return bool(json.loads(m["settings_json"] or "{}").get("host_paid"))
    except (ValueError, TypeError):
        return False


def is_web_event(m):
    """True for a self-serve 'run your own event' meet (owned by the XCTimer Web org).
    Self-serve races time by tap-then-scan with camera-readable ArUco tags — no QR bibs."""
    try:
        oid = m["organizer_id"]
    except (KeyError, IndexError, TypeError):
        return False
    if not oid:
        return False
    conn = db.connect()
    try:
        return oid == _web_org_id(conn)
    finally:
        conn.close()


def _owner_uid(row):
    try:
        return json.loads(row["settings_json"] or "{}").get("owner_user_id")
    except (ValueError, TypeError):
        return None


def _host_page(title, inner):
    return (f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · XCTimer</title>{HEAD_EXTRA}<script>{CSRF_JS}</script>
<style>body{{font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f8fc;color:#20303f;margin:0}}
.wrap{{max-width:560px;margin:0 auto;padding:1.4rem 1.1rem 3rem}}
.card{{background:#fff;border:1px solid #e3e9f1;border-radius:12px;padding:1.1rem;margin:0 0 1rem}}
label{{display:block;font-weight:600;margin:.6rem 0 .2rem}}
input,button{{font:inherit}} input{{width:100%;padding:.55rem;border:1px solid #cdd7e2;border-radius:8px}}
.btn{{background:#ea6a2d;color:#fff;border:0;border-radius:9px;padding:.7rem 1.3rem;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}}
h1{{color:#164271;margin-top:0}} a{{color:#164271}}</style></head><body><div class="wrap">
<p><a href="/">← XCTimer</a></p>{inner}</div></body></html>""")


@bp.get("/host")
def host_start():
    fee = _fee_str(HOST_FEE_CENTS)
    inner = (f"""<h1>Run your own fun run</h1>
<p>Set up a community 5K / 10K / fun run yourself — a public sign-up page, printed bibs, phone or
camera timing, and live results the whole crowd can follow. <b>{fee} per event</b>, paid when you
open registration.</p>
<div class="card"><form method="post" action="/host">
<label>Event name</label><input name="name" required placeholder="e.g. Maple Grove Community 5K">
<label>Event date</label><input name="date" type="date" required>
<label>Your name</label><input name="who" required>
<label>Your email</label><input name="email" type="email" required>
<p style="font-size:.85rem;color:#6a7c8e">We'll email you a private link to build and manage your event.</p>
<button class="btn" type="submit">Create my event →</button>
</form></div>
<div class="card"><b>Already started one?</b>
<form method="post" action="/host/resend" style="display:flex;gap:.5rem;margin-top:.4rem">
<input name="email" type="email" placeholder="your email" required>
<button class="btn" type="submit" style="white-space:nowrap;background:#3d6fa5">Email my link</button></form></div>""")
    return _host_page("Run your own fun run", inner)


def _send_host_link(email, token):
    from .auth import send_email, _public_url
    link = f"{_public_url()}/host/go/{token}"
    send_email(email, "Your XCTimer event link",
               f"<p>Here's your private link to build and manage your XCTimer event:</p>"
               f'<p><a href="{link}">{link}</a></p>'
               f"<p>Keep it private — anyone with the link can edit your event.</p>")
    return link


def _email_existing_host(email):
    """Regenerate + email the magic link for an existing host. Returns True if one existed."""
    from .auth import _iso, _now
    conn = db.connect()
    web = _web_org_id(conn)
    u = conn.execute("SELECT id FROM users WHERE email=? AND organizer_id=?", (email, web)).fetchone()
    if not u:
        conn.close()
        return False
    token = secrets.token_urlsafe(32)
    conn.execute("UPDATE users SET setup_token=?, token_expires=? WHERE id=?",
                 (token, _iso(_now() + timedelta(days=60)), u["id"]))
    conn.commit()
    conn.close()
    _send_host_link(email, token)
    return True


@bp.post("/host")
def host_create():
    from .auth import _iso, _now
    name = (request.form.get("name") or "").strip()
    date = (request.form.get("date") or "").strip() or None
    who = (request.form.get("who") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    if not name or "@" not in email:
        return _host_page("Run your own fun run",
                          '<div class="card">Please enter an event name and a valid email. '
                          '<a href="/host">← Back</a></div>'), 400
    conn = db.connect()
    web = _web_org_id(conn)
    # users.email is globally unique, so we must check ALL accounts — not just web-org hosts —
    # before inserting, or an email that already belongs to a coach/admin 500s on the constraint.
    existing = conn.execute("SELECT id, organizer_id FROM users WHERE email=?", (email,)).fetchone()
    if existing and existing["organizer_id"] == web:
        conn.close()
        _email_existing_host(email)   # returning host -> just resend the link
        return _host_page("Check your email",
                          f'<div class="card"><h1>Check your email</h1><p>You already have an event under '
                          f'<b>{escape(email)}</b> — we re-sent your private link.</p></div>')
    if existing:
        conn.close()
        return _host_page("Email already in use",
                          f'<div class="card"><h1>That email is already registered</h1>'
                          f'<p><b>{escape(email)}</b> already has an XCTimer login, so we can’t create a '
                          f'separate community-event sign-in for it. Please <a href="/host">go back</a> and use '
                          f'a different email to host your event.</p></div>'), 400
    token = secrets.token_urlsafe(32)
    uid = conn.execute(
        "INSERT INTO users (organizer_id, email, name, role, setup_token, token_expires) "
        "VALUES (?,?,?,?,?,?)",
        (web, email, who or name, "race_director", token, _iso(_now() + timedelta(days=60)))).lastrowid
    mid = conn.execute(
        "INSERT INTO meets (organizer_id, sport, name, date, public_token, team_scoring, settings_json) "
        "VALUES (?,?,?,?,?,0,?)",
        (web, "road", name, date, secrets.token_urlsafe(8),
         json.dumps({"host_paid": False, "owner_user_id": uid, "owner_email": email}))).lastrowid
    conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)", (mid, "5K", "tapselect"))
    conn.commit()
    conn.close()
    _send_host_link(email, token)
    return _host_page("Check your email",
                      f'<div class="card"><h1>✅ Check your email</h1><p>We emailed <b>{escape(email)}</b> a '
                      f'private link to build and manage <b>{escape(name)}</b>. Tap it to get started.</p></div>')


@bp.post("/host/resend")
def host_resend():
    email = (request.form.get("email") or "").strip().lower()
    _email_existing_host(email)   # silent regardless (no account enumeration)
    return _host_page("Check your email",
                      '<div class="card"><h1>Check your email</h1><p>If an event exists for that address, '
                      'we just emailed its private link.</p></div>')


@bp.get("/host/go/<token>")
def host_go(token):
    from .auth import create_session, SESSION_COOKIE, _now, _parse
    conn = db.connect()
    web = _web_org_id(conn)
    u = conn.execute("SELECT * FROM users WHERE setup_token=? AND organizer_id=?", (token, web)).fetchone()
    if not u:
        conn.close()
        return _host_page("Link not found",
                          '<div class="card"><h1>Link not found</h1><p>That link is invalid. '
                          '<a href="/host">Start over or email a fresh link</a>.</p></div>'), 404
    exp = _parse(u["token_expires"]) if u["token_expires"] else None
    if exp and exp < _now():
        conn.close()
        return _host_page("Link expired",
                          '<div class="card"><h1>Link expired</h1>'
                          '<p><a href="/host">Email a fresh link</a>.</p></div>'), 410
    rows = conn.execute("SELECT id, settings_json FROM meets WHERE organizer_id=?", (web,)).fetchall()
    conn.close()
    m = next((r for r in rows if _owner_uid(r) == u["id"]), None)
    if not m:
        return _host_page("No event", '<div class="card">No event found for this link.</div>'), 404
    tok = create_session(u["id"], kind="event_owner", meet_id=m["id"], ttl_days=60)
    resp = make_response(redirect(f"/meets/{m['id']}"))
    resp.set_cookie(SESSION_COOKIE, tok, httponly=True, samesite="Lax",
                    secure=bool(os.environ.get("XC_SECURE_COOKIES")), max_age=60 * 24 * 3600)
    return resp


@bp.post("/meets/<int:mid>/host-publish")
@login_required
def host_publish(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    s = _load_settings(mid)
    s["host_paid"] = True     # honor-system Venmo confirmation
    _save_settings(mid, s)
    return redirect(f"/meets/{mid}")


@bp.post("/meets/<int:mid>/host-pay-square")
@login_required
def host_pay_square(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    from . import square
    if not square.is_configured():
        return jsonify(error="Card payments aren’t set up yet — use Venmo."), 400
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    ret = f"{base}/meets/{mid}/host-square-return"
    try:
        url = square.create_payment_link(f"XCTimer event — {m['name']}", HOST_FEE_CENTS,
                                          ret, f"xctimer_meet={mid}")
    except Exception:
        logging.getLogger("xctimer.road").exception("host_pay_square failed for meet %s", mid)
        return jsonify(error="Couldn’t start Square checkout — try again, or use Venmo."), 502
    # Return the URL for the client to navigate to. A form POST that 302s to Square is blocked by
    # our CSP (form-action 'self'); a JS location.href navigation is not, so the button uses jpost.
    return jsonify(url=url)


@bp.get("/meets/<int:mid>/host-square-return")
@login_required
def host_square_return(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    from . import square
    oid = request.args.get("orderId") or ""
    if square.order_ok(oid, expect_note_substr=f"xctimer_meet={mid}"):
        _mark_host_paid(mid, oid)
        return redirect(f"/meets/{mid}?paid=1")
    return redirect(f"/meets/{mid}?payerr=1")


def _mark_host_paid(mid, order_id):
    s = _load_settings(mid)
    if not s.get("host_paid"):
        s["host_paid"] = True
        s["square_order_id"] = order_id
        _save_settings(mid, s)


@bp.post("/square/webhook")
def square_webhook():
    """Square server-to-server callback (HMAC-verified; CSRF-exempt). A COMPLETED
    payment.updated auto-publishes the event even if the buyer never returns to the
    redirect URL — the bulletproof path."""
    from . import square
    body = request.get_data()
    sig = request.headers.get("X-Square-Hmacsha256-Signature", "")
    notif = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/")) + "/square/webhook"
    if not square.verify_webhook_signature(body, sig, notif):
        abort(401)
    try:
        evt = json.loads(body.decode() or "{}")
    except ValueError:
        return ("", 200)
    if evt.get("type") in ("payment.updated", "payment.created"):
        pay = (evt.get("data", {}).get("object", {}) or {}).get("payment", {}) or {}
        if pay.get("status") == "COMPLETED" and pay.get("order_id"):
            mid = square.order_meet_id(pay["order_id"])
            if mid:
                _mark_host_paid(mid, pay["order_id"])
    return ("", 200)


def host_banner(m):
    """Pay-to-go-live banner shown on a self-serve web event until the $50 is paid."""
    if not _is_org(m):
        return ""
    conn = db.connect()
    web = _web_org_id(conn)
    conn.close()
    if m["organizer_id"] != web:
        return ""
    fee = _fee_str(HOST_FEE_CENTS)
    mid = m["id"]
    if host_paid(m):
        return ('<div class="card" style="border-color:#2e8b57"><b style="color:#2e8b57">✅ '
                'Published.</b> <span class="muted">Registration can be opened in the settings below.</span></div>')
    from . import square
    msg = ('<p style="color:var(--err);font-weight:600;margin:.2rem 0">⚠ Payment didn\'t complete — '
           'try again, or use Venmo.</p>') if request.args.get("payerr") else ""
    # Verified card payment via Square (auto-publishes on a completed order).
    sq = ""
    if square.is_configured():
        # NB not a <form> that POSTs+redirects: CSP form-action 'self' blocks the cross-origin
        # redirect to square.link. jpost returns the URL and we navigate via location.href.
        sq = (f'<button type="button" id="sqpay" onclick="paySquare()" '
              f'style="background:#006aff;color:#fff;border:0;border-radius:9px;padding:.55rem 1rem;'
              f'font-weight:700;cursor:pointer">💳 Pay {fee} with Square (card)</button>'
              f'<script>async function paySquare(){{var b=document.getElementById("sqpay");'
              f'b.disabled=true;b.textContent="Starting checkout…";'
              f'try{{var j=await jpost("/meets/{mid}/host-pay-square",{{}});'
              f'if(j&&j.url){{location.href=j.url;return;}}throw new Error("no url");}}'
              f'catch(e){{b.disabled=false;b.textContent="💳 Pay {fee} with Square (card)";'
              f'alert(e.message||"Checkout failed — try again or use Venmo.");}}}}</script>')
    # Venmo (honor-system) fallback — needs the manual "I've sent it" confirmation.
    handle = os.environ.get("XC_HOST_VENMO", "").lstrip("@")
    vpay = ""
    if handle:
        vurl = _venmo_url(handle, HOST_FEE_CENTS, f"XCTimer event: {m['name']}")
        vpay = (f'<a class="btn" href="{escape(vurl)}" target="_blank" '
                f'style="background:#3d95ce;color:#fff;padding:.55rem 1rem;border-radius:9px;'
                f'text-decoration:none;font-weight:700">Pay {fee} with Venmo</a>'
                f'<form class="inline" method="post" action="/meets/{mid}/host-publish" style="display:inline" '
                f'onsubmit="return confirm(\'Confirm you sent the {fee} via Venmo — this publishes your event.\')">'
                f'<button class="ghost">I\'ve sent Venmo — publish</button></form>')
    none_note = ('<span class="muted">Payment isn\'t configured yet — contact XCTimer.</span>'
                 if not (square.is_configured() or handle) else "")
    return (f'<div class="card" style="border:2px solid #ea6a2d">'
            f'<h2 style="margin-top:0">🚦 Go live — {fee} per event</h2>'
            f'<p style="margin:.2rem 0 .6rem">Build your event below. When you\'re ready to open '
            f'registration and time the race, pay the {fee} event fee. Card (Square) is verified '
            f'instantly; Venmo is on your honor.</p>{msg}'
            f'<div style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:center">{sq}{vpay}{none_note}</div></div>')


def reap_web_events(conn, today_iso):
    """Delete self-serve web events (and their owner logins) 30+ days after the event date.
    `today_iso` = 'YYYY-MM-DD' passed in (no wall-clock in callers that need determinism)."""
    web = conn.execute("SELECT id FROM organizers WHERE slug='xctimer-web'").fetchone()
    if not web:
        return 0
    from datetime import date as _date, timedelta as _td
    cutoff = (_date.fromisoformat(today_iso) - _td(days=30)).isoformat()
    rows = conn.execute(
        "SELECT id, settings_json FROM meets WHERE organizer_id=? AND date IS NOT NULL AND date < ?",
        (web["id"], cutoff)).fetchall()
    n = 0
    for r in rows:
        owner = _owner_uid(r)
        _purge_meet(conn, r["id"])
        if owner:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (owner,))
            conn.execute("DELETE FROM users WHERE id=?", (owner,))
        n += 1
    conn.commit()
    return n


# ============================ self-serve setup assistant (Claude) ============================
_HOST_HELP_SYS = """You are "the Ref" — a friendly, straight-talking race official who helps
organizers set up and run their community race (a 5K/10K/fun run) on XCTimer. Talk like a helpful
official: clear, encouraging, plain-spoken, a little playful. Keep answers short, concrete, and
specific to XCTimer. Only answer questions about using XCTimer to plan, build, and run their event
— for anything unrelated, politely blow the whistle and steer back. Never invent features; if
unsure, tell them to email admin@xctimer.com.

How XCTimer self-serve works (rely on these facts):
- Create an event at xctimer.com/host; you get a private email link to manage it (bookmark it, or
  use "Email my link" on /host to get it again).
- Setup tab: add your races (e.g. 5K, 10K, Fun Run); set Default age groups (e.g.
  "10 & Under, 11-14, 15-19, 20-29, 30+"); upload your event logo; optionally set an Entry fee and
  your Venmo so runners pay you when they register. Timing is always tap-then-scan (no mode to pick).
- Go live: $50 per event. Build it free, then pay the $50 by card (Square — instant) or Venmo to
  open registration. Registration stays closed until you pay.
- Public registration: share the registration link/QR; runners self-register (name, age, gender,
  city, club) and pick their race — no account needed.
- Participants tab: import a CSV, add runners by hand, or let them self-register. Print bibs here on
  Avery 5163 (2"x4") sticker sheets — camera-readable ArUco tags — with your logo, plus a few blank
  spares for walk-ups.
- Race day tab: the Phone Timer App — share its QR/link with helpers to open the timing app for your
  event, no login. Timing is tap-then-scan: a helper taps each runner as they cross the finish line
  (captures time + order), then you scan or type each runner's bib to attach names — this works even
  after you stop the clock. There's also a finish-line camera that reads the ArUco bib tags.
- Results: live, by gender x age group; share the public results link/QR with the crowd.
- Your event auto-deletes 30 days after the event date.

Be encouraging and practical. Prefer step-by-step answers a first-time race director can follow."""


@bp.post("/host/chat")
@login_required
def host_chat():
    """Setup-assistant chat for self-serve event owners (uses the Anthropic key)."""
    p = g.principal
    if getattr(p, "owns_meet", None) is None and not p.is_super:
        abort(403)
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or "").strip()[:1000]
    history = data.get("history") if isinstance(data.get("history"), list) else []
    if not msg:
        return jsonify(reply="Ask me anything about setting up or running your event!")
    from . import ai
    try:
        reply = ai.claude_chat(_HOST_HELP_SYS, msg, history=history, max_tokens=700)
    except Exception:
        return jsonify(reply="Sorry — the assistant is unavailable right now. "
                             "Email admin@xctimer.com and we'll help."), 200
    return jsonify(reply=reply or "(no answer)")


def host_chat_widget():
    """Floating 'Ask the Ref' chat (referee-styled), injected by ui.shell for event owners only."""
    return """
<div id="hcbtn" onclick="hcToggle()" style="position:fixed;right:18px;bottom:18px;z-index:9998;
  display:flex;align-items:center;gap:.5rem;background:#141414;color:#fff;border:2px solid #fff;
  border-radius:999px;padding:.5rem .95rem .5rem .5rem;font-weight:800;cursor:pointer;
  box-shadow:0 4px 16px rgba(0,0,0,.35)">
  <span style="width:1.6rem;height:1.6rem;border-radius:50%;border:2px solid #fff;flex-shrink:0;
    background:repeating-linear-gradient(90deg,#111 0 6px,#fff 6px 12px)"></span>Ask the Ref</div>
<div id="hcpanel" style="display:none;position:fixed;right:18px;bottom:78px;z-index:9998;
  width:min(370px,92vw);height:min(480px,72vh);background:#fff;color:#20303f;border-radius:14px;
  box-shadow:0 8px 30px rgba(0,0,0,.45);flex-direction:column;overflow:hidden;border:2px solid #141414">
  <div style="height:9px;background:repeating-linear-gradient(90deg,#111 0 6px,#fff 6px 12px)"></div>
  <div style="background:#141414;color:#fff;padding:.55rem .9rem;font-weight:800;display:flex;
    justify-content:space-between;align-items:center">
    <span>&#129370; The Ref</span>
    <span onclick="hcToggle()" style="cursor:pointer">&#10005;</span></div>
  <div id="hclog" style="flex:1;overflow-y:auto;padding:.7rem;font-size:.9rem;background:#fafafa">
    <div style="background:#eef1f4;border-left:3px solid #141414;border-radius:8px;padding:.5rem .7rem;margin:.3rem 0">
      &#129370; I&#39;m the Ref. Ask me anything about setting up or running your race &mdash;
      bibs, registration, timing, going live, results&hellip;</div>
  </div>
  <div style="display:flex;gap:.4rem;padding:.6rem;border-top:1px solid #e3e9f1">
    <input id="hcin" placeholder="Ask the Ref&hellip;"
      style="flex:1;padding:.5rem;border:1px solid #cdd7e2;border-radius:8px;font:inherit"
      onkeydown="if(event.key==='Enter')hcSend()">
    <button onclick="hcSend()" style="background:#141414;color:#fff;border:0;border-radius:8px;
      padding:.5rem .9rem;font-weight:800;cursor:pointer">Send</button>
  </div>
</div>
<script>
var HCHIST=[];
function hcToggle(){var p=document.getElementById('hcpanel');
  p.style.display=(p.style.display==='none'||!p.style.display)?'flex':'none';
  if(p.style.display==='flex')document.getElementById('hcin').focus();}
function hcCsrf(){var m=document.cookie.match(/csrftoken=([^;]+)/);return m?decodeURIComponent(m[1]):'';}
function hcAdd(role,text){var l=document.getElementById('hclog');var d=document.createElement('div');
  d.style.cssText='border-radius:8px;padding:.5rem .7rem;margin:.3rem 0;white-space:pre-wrap;'
    +(role==='user'?'background:#141414;color:#fff;margin-left:2rem'
                   :'background:#eef1f4;border-left:3px solid #141414;margin-right:1rem');
  d.textContent=text;l.appendChild(d);l.scrollTop=l.scrollHeight;return d;}
async function hcSend(){var i=document.getElementById('hcin');var q=i.value.trim();if(!q)return;
  i.value='';hcAdd('user',q);var t=hcAdd('bot','\u2026');
  try{var r=await fetch('/host/chat',{method:'POST',
      headers:{'Content-Type':'application/json','X-CSRF-Token':hcCsrf()},
      body:JSON.stringify({message:q,history:HCHIST})});
    var j=await r.json();t.textContent=j.reply||'(no reply)';
    HCHIST.push({role:'user',content:q});HCHIST.push({role:'assistant',content:j.reply||''});
    if(HCHIST.length>16)HCHIST=HCHIST.slice(-16);}
  catch(e){t.textContent='Sorry, something went wrong. Try again.';}}
</script>"""
