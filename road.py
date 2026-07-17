"""Community road-race world: Organizers (a tenant separate from school districts),
their race-director logins, and Events. An event is a `meets` row owned by an
organizer (district_id NULL, sport='road') — so it reuses the whole timing/results
engine, minus schools, rosters, and PII.
"""
import csv
import io
import json
import os
import re
import secrets

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, Response

from . import db
from .auth import login_required, role_required, create_user, send_setup_email
from .meets import load_meet, can_view_meet, can_setup_meet
from .xc import _is_org, _match_event
from .ui import shell, CSRF_JS, BRAND_HTML, HEAD_EXTRA

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
    # Community road races are camera/scan-first — each read records a new finisher.
    conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)",
                 (mid, race_name, "scan"))
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
    _event_or_403(mid, can_setup_meet)
    s = _load_settings(mid)
    s["reg_open"] = bool(request.form.get("reg_open"))
    s["reg_text"] = (request.form.get("reg_text") or "").strip()
    fee = (request.form.get("fee") or "").strip()
    try:
        s["fee_cents"] = int(round(float(fee) * 100)) if fee else 0
    except ValueError:
        s["fee_cents"] = 0
    _save_settings(mid, s)
    return redirect(f"/meets/{mid}")


@bp.get("/meets/<int:mid>/participants/stickers.pdf")
@login_required
def participant_stickers(mid):
    m = _event_or_403(mid, can_view_meet)
    template = request.args.get("template", "5160")
    s = _load_settings(mid)
    conn = db.connect()
    ps = conn.execute(
        "SELECT bib, name FROM participants WHERE meet_id=? AND bib IS NOT NULL ORDER BY bib",
        (mid,)).fetchall()
    conn.close()
    from . import pdfs
    # code='aruco' -> the camera-readable tag replaces the QR (bib <= 1023).
    athletes = [{"bib": p["bib"], "name": p["name"], "code": "aruco"} for p in ps]
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
    fee_card = (f'<div class="card fee">Entry fee: {_fee_str(fee)} per runner — '
                f'collected at packet pickup.</div>' if fee else "")
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
    fee_line = (f'<div class="card fee">Amount due at packet pickup: '
                f'{_fee_str(fee * len(created))} ({len(created)} × {_fee_str(fee)}).</div>' if fee else "")
    inner = (f'<div class="card"><h2 style="margin-top:0;color:#2e8b57">✅ You\'re registered!</h2>'
             f'<p>See you on race day. Your bib number(s):</p><ul>{rows}</ul></div>'
             f'{fee_line}'
             f'<div style="text-align:center"><a href="/register/{escape(token)}">'
             f'Register more runners</a></div>')
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
