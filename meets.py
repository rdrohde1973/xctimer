"""Meets: CRUD, attending schools, host, public token, meet-day QR (handoff §8).

A meet has a sport ('xc'|'track'). Phase 3 wires the XC engine (xc.py); track
is Phase 4. Access:
  - view:   super | district_admin(own) | coach attending
  - setup:  super | district_admin(own) | coach who hosts
  - record: super | district_admin(own) | coach attending | meet-QR principal
"""
import io
import json
import secrets
from datetime import datetime, timezone

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, Response

import os

from . import db, pdfs
from .auth import login_required
from .tenancy import active_district_id, all_districts
from .ui import shell

bp = Blueprint("meets", __name__)


def _road_enabled(did):
    """Whether the Road-race sport is turned on for this district (super-admin gated)."""
    if did is None:
        return False
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    conn.close()
    try:
        return bool(json.loads((d["settings_json"] if d else None) or "{}").get("road_enabled"))
    except (ValueError, TypeError):
        return False


def _now():
    return datetime.now(timezone.utc)


def _districts_for_switcher():
    return all_districts() if g.principal.is_super else None


# ------------------------------- access -------------------------------
def load_meet(mid):
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m:
        abort(404)
    return m


def meet_school_ids(mid):
    conn = db.connect()
    rows = conn.execute("SELECT school_id FROM meet_schools WHERE meet_id=?", (mid,)).fetchall()
    conn.close()
    return {r[0] for r in rows}


def _meet_organizer_id(m):
    return m["organizer_id"] if "organizer_id" in m.keys() else None


def can_view_meet(m):
    p = g.principal
    if not p:
        return False
    if p.meet_scope:
        return p.meet_scope == m["id"]
    if p.is_super:
        return True
    org = _meet_organizer_id(m)
    if org is not None:                       # community road event: organizer-scoped
        return getattr(p, "organizer_id", None) == org
    if p.district_id != m["district_id"]:
        return False
    if p.role == "district_admin":
        return True
    if p.role in ("coach", "timer"):
        return bool(p.school_ids() & meet_school_ids(m["id"])) or m["host_school_id"] in p.school_ids()
    return False


def can_setup_meet(m):
    p = g.principal
    if not p or p.meet_scope:
        return False
    if p.is_super:
        return True
    org = _meet_organizer_id(m)
    if org is not None:
        return getattr(p, "organizer_id", None) == org
    if p.district_id != m["district_id"]:
        return False
    if p.role == "district_admin":
        return True
    if p.role == "coach":
        return m["host_school_id"] in p.school_ids()
    return False


def can_record_meet(m):
    p = g.principal
    if not p:
        return False
    if p.meet_scope:
        return p.meet_scope == m["id"]
    if p.is_super:
        return True
    org = _meet_organizer_id(m)
    if org is not None:
        return getattr(p, "organizer_id", None) == org
    if p.district_id != m["district_id"]:
        return False
    if p.role in ("district_admin",):
        return True
    if p.role in ("coach", "timer"):
        return bool(p.school_ids() & meet_school_ids(m["id"])) or m["host_school_id"] in p.school_ids()
    return False


def _district_schools(did):
    conn = db.connect()
    rows = conn.execute("SELECT * FROM schools WHERE district_id=? ORDER BY name", (did,)).fetchall()
    conn.close()
    return rows


# ------------------------------- list + create -------------------------------
@bp.get("/meets")
@login_required
def list_meets():
    p = g.principal
    if p.meet_scope:
        return redirect("/dashboard")
    did = active_district_id()
    conn = db.connect()
    if p.is_super and did is None:
        rows = conn.execute(
            "SELECT m.*, d.name AS dname FROM meets m JOIN districts d ON d.id=m.district_id "
            "WHERE m.organizer_id IS NULL ORDER BY m.date DESC, m.name").fetchall()
    else:
        rows = conn.execute(
            "SELECT m.*, NULL AS dname FROM meets m WHERE m.district_id=? AND m.organizer_id IS NULL "
            "ORDER BY m.date DESC, m.name", (did,)).fetchall()
    conn.close()
    rows = [m for m in rows if can_view_meet(m)]

    show_d = p.is_super and did is None
    show_x = p.is_admin   # super / district admin get a delete X per row
    trs = []
    for m in rows:
        sport = {"xc": "🏃 XC", "track": "🎽 Track", "road": "🛣 Road"}.get(m["sport"], "🎽 Track")
        dcol = f'<td>{escape(m["dname"])}</td>' if show_d else ""
        xcol = ""
        if show_x:
            x = ""
            if can_delete_meet(m):
                x = (f'<form class="inline" method="post" action="/meets/{m["id"]}/delete" '
                     f'onsubmit="return confirm(\'Delete this meet and ALL its data — heats, '
                     f'entries, results, and timing? This cannot be undone.\')">'
                     f'<button class="danger" style="padding:.2rem .5rem;line-height:1" '
                     f'title="Delete meet">✕</button></form>')
            xcol = f'<td style="text-align:right">{x}</td>'
        trs.append(f'<tr><td><b><a href="/meets/{m["id"]}">{escape(m["name"])}</a></b></td>'
                   f'<td>{sport}</td><td>{escape(m["date"] or "")}</td>{dcol}{xcol}</tr>')
    hdr = (f'<tr><th>Meet</th><th>Sport</th><th>Date</th>'
           f'{"<th>District</th>" if show_d else ""}{"<th></th>" if show_x else ""}</tr>')
    table = (f'<div class="card"><table>{hdr}{"".join(trs)}</table></div>'
             if rows else '<div class="card muted">No meets yet.</div>')

    form = ""
    can_create = p.is_admin   # only super / district admins create meets
    road_opt = ('<option value="road">Road race</option>' if _road_enabled(did) else '')
    if can_create and not (p.is_super and did is None):
        schools = _district_schools(did)
        host_opts = '<option value="">— none —</option>' + "".join(
            f'<option value="{s["id"]}">{escape(s["name"])}</option>' for s in schools)
        att = "".join(
            f'<label style="display:flex;gap:.5rem;align-items:center;font-size:.95rem">'
            f'<input type="checkbox" name="school_ids" value="{s["id"]}" style="width:auto">'
            f'{escape(s["name"])}</label>' for s in schools)
        form = f"""
<div class="card"><h2>Create a meet</h2>
<form method="post" action="/meets">
  <div class="row">
    <div><label>Name</label><input name="name" required></div>
    <div style="max-width:140px"><label>Sport</label>
      <select name="sport"><option value="xc">Cross-country</option>
      <option value="track">Track &amp; Field</option>{road_opt}</select></div>
    <div style="max-width:170px"><label>Date</label><input name="date" type="date" required></div>
  </div>
  <label>Host school</label><select name="host_school_id">{host_opts}</select>
  <label>Attending schools</label>
  <div class="card" style="background:var(--panel2);max-height:180px;overflow:auto">{att or '<span class="muted">Add schools first.</span>'}</div>
  <button type="submit" style="margin-top:1rem">Create meet</button>
</form></div>"""
    elif p.is_super and did is None:
        form = '<p class="muted">Pick a district in the header to create a meet.</p>'

    from .phone import _install_card
    body = (f'<div class="row" style="justify-content:space-between;align-items:center">'
            f"<div><h1>Meets</h1><p class='sub'>Cross-country &amp; track meets.</p></div>"
            f'<a class="btn ghost" href="/bibcheck">🔍 Bib check</a></div>'
            f"{_install_card()}{table}{form}")
    return shell(p, body, active="meets", active_district=did, districts=_districts_for_switcher())


@bp.post("/meets")
@login_required
def create_meet():
    p = g.principal
    did = active_district_id()
    if did is None:
        abort(400)
    if not p.is_admin:   # only super / district admins create meets
        abort(403)
    name = (request.form.get("name") or "").strip()
    allowed_sports = ("xc", "track") + (("road",) if _road_enabled(did) else ())
    sport = request.form.get("sport") if request.form.get("sport") in allowed_sports else "xc"
    date = (request.form.get("date") or "").strip()
    if not name or not date:
        abort(400)
    host = (request.form.get("host_school_id") or "").strip()
    host = int(host) if host.isdigit() else None
    school_ids = [int(x) for x in request.form.getlist("school_ids") if x.isdigit()]

    conn = db.connect()
    # validate schools belong to district
    valid = {r[0] for r in conn.execute(
        "SELECT id FROM schools WHERE district_id=?", (did,)).fetchall()}
    school_ids = [s for s in school_ids if s in valid]
    if host is not None and host not in valid:
        host = None
    cur = conn.execute(
        "INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token) "
        "VALUES (?,?,?,?,?,?)",
        (did, sport, name, date, host, secrets.token_urlsafe(8)))
    mid = cur.lastrowid
    for s in set(school_ids) | ({host} if host else set()):
        conn.execute("INSERT OR IGNORE INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, s))
    if sport == "xc":
        # Auto-create the two standard heats (like the reference XC app).
        for hn in ("Boys", "Girls"):
            conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)",
                         (mid, hn, "tap"))
    elif sport == "road":
        # Road: individual placing by gender × age group, no team scoring.
        # Events (5K, 10K, …) are added by the organizer in setup — each is its own race.
        conn.execute("UPDATE meets SET team_scoring=0 WHERE id=?", (mid,))
    else:
        pt = conn.execute("SELECT id FROM points_tables WHERE name=?",
                          ("Invitational 10-8-6-4-2-1",)).fetchone()
        if pt:
            conn.execute("UPDATE meets SET points_table_id=? WHERE id=?", (pt[0], mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


def can_delete_meet(m):
    """Deleting a meet is Super Admin / District Admin (own district) only."""
    p = g.principal
    if not p or p.meet_scope:
        return False
    return p.is_admin and (p.is_super or p.district_id == m["district_id"])


@bp.post("/meets/<int:mid>/delete")
@login_required
def delete_meet(mid):
    m = load_meet(mid)
    if not can_delete_meet(m):
        abort(403)
    conn = db.connect()
    # Track data: results -> entries -> meet_events (+ live tap-timer state, which has
    # no FK — left behind it could attach to a future event that reuses the rowid)
    conn.execute("DELETE FROM results WHERE entry_id IN (SELECT en.id FROM entries en "
                 "JOIN meet_events me ON me.id=en.meet_event_id WHERE me.meet_id=?)", (mid,))
    conn.execute("DELETE FROM track_taps WHERE meet_event_id IN "
                 "(SELECT id FROM meet_events WHERE meet_id=?)", (mid,))
    conn.execute("DELETE FROM track_clocks WHERE meet_event_id IN "
                 "(SELECT id FROM meet_events WHERE meet_id=?)", (mid,))
    conn.execute("DELETE FROM entries WHERE meet_event_id IN "
                 "(SELECT id FROM meet_events WHERE meet_id=?)", (mid,))
    conn.execute("DELETE FROM meet_events WHERE meet_id=?", (mid,))
    # XC / road data: finishers + road assignments + community participants -> races
    conn.execute("DELETE FROM finishers WHERE race_id IN (SELECT id FROM races WHERE meet_id=?)", (mid,))
    conn.execute("DELETE FROM race_entries WHERE meet_id=?", (mid,))
    conn.execute("DELETE FROM participants WHERE meet_id=?", (mid,))
    conn.execute("DELETE FROM races WHERE meet_id=?", (mid,))
    conn.execute("DELETE FROM meet_schools WHERE meet_id=?", (mid,))
    conn.execute("DELETE FROM meets WHERE id=?", (mid,))
    conn.commit()
    conn.close()
    return redirect("/meets")


@bp.post("/meets/<int:mid>/schools")
@login_required
def update_meet_schools(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    school_ids = [int(x) for x in request.form.getlist("school_ids") if x.isdigit()]
    conn = db.connect()
    valid = {r[0] for r in conn.execute(
        "SELECT id FROM schools WHERE district_id=?", (m["district_id"],)).fetchall()}
    conn.execute("DELETE FROM meet_schools WHERE meet_id=?", (mid,))
    for s in school_ids:
        if s in valid:
            conn.execute("INSERT OR IGNORE INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, s))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


# ------------------------------- meet-day QR -------------------------------
@bp.post("/meets/<int:mid>/timer-qr")
@login_required
def gen_timer_qr(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    token = secrets.token_urlsafe(10)
    # No date expiry — the link opens this one meet's timing anytime (revoke by rotating).
    conn = db.connect()
    conn.execute("UPDATE meets SET timer_token=?, timer_token_expires=NULL WHERE id=?",
                 (token, mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


@bp.get("/meets/<int:mid>/timer-qr.png")
@login_required
def timer_qr_png(mid):
    import qrcode
    m = load_meet(mid)
    if not can_view_meet(m) or not m["timer_token"]:
        abort(404)
    import os
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    url = f"{base}/t/{m['timer_token']}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


# ------------------------------- detail (setup shell) -------------------------------
@bp.get("/meets/<int:mid>")
@login_required
def meet_detail(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    conn = db.connect()
    att = conn.execute(
        "SELECT s.* FROM schools s JOIN meet_schools ms ON ms.school_id=s.id "
        "WHERE ms.meet_id=? ORDER BY s.name", (mid,)).fetchall()
    all_sch = conn.execute("SELECT * FROM schools WHERE district_id=? ORDER BY name",
                           (m["district_id"],)).fetchall()
    host = conn.execute("SELECT name FROM schools WHERE id=?", (m["host_school_id"],)).fetchone() \
        if m["host_school_id"] else None
    conn.close()

    att_ids = {s["id"] for s in att}
    setup = can_setup_meet(m)
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    is_xc = m["sport"] in ("xc", "road")   # road reuses the XC race engine
    is_org = ("organizer_id" in m.keys() and m["organizer_id"] is not None)
    # Results / Public / Export live on the Results tab — not duplicated here.

    hs = (f' <a class="btn ghost" href="/meets/{mid}/heatsheets.pdf">Heat sheets</a>'
          if not is_xc else "")
    # Track stickers carry each athlete's events, which don't fit Avery 5160 — 5163 only.
    if is_xc:
        sticker_btns = (
            f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5160">Stickers 5160</a> '
            f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5163">Stickers 5163</a> ')
    else:
        sticker_btns = f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5163">Stickers (5163)</a> '
    print_bar = "" if is_org else (
        f'<div class="card"><b>Print — all attending schools:</b> '
        f'{sticker_btns}'
        f'<a class="btn ghost" href="/meets/{mid}/biblist.pdf">Bib lists</a>{hs}</div>')

    if is_xc:
        from . import xc as _sport
    else:
        from . import track as _sport

    host_label = ('Host school <span class="muted">— only the host school\'s coaches '
                  'can run this meet</span>')
    if setup:
        boxes = "".join(
            f'<label style="display:flex;gap:.5rem;align-items:center;font-size:.95rem">'
            f'<input type="checkbox" name="school_ids" value="{s["id"]}" style="width:auto" '
            f'{"checked" if s["id"] in att_ids else ""}>{escape(s["name"])}</label>' for s in all_sch)
        hopts = '<option value="">— none —</option>' + "".join(
            f'<option value="{s["id"]}" {"selected" if s["id"]==m["host_school_id"] else ""}>'
            f'{escape(s["name"])}</option>' for s in all_sch)
        if is_xc:
            setup_card = (
                '<div class="card"><h2>Schools at this meet</h2>'
                f'<form method="post" action="/meets/{mid}/schools">'
                f'<div class="card" style="background:var(--panel2)">{boxes}</div>'
                f'<button type="submit" style="margin-top:.6rem">Save attending</button></form>'
                f'<form method="post" action="/meets/{mid}/host" style="margin-top:.9rem">'
                f'<label>{host_label}</label>'
                f'<div class="row"><div style="max-width:260px"><select name="host_school_id">{hopts}</select></div>'
                f'<div style="display:flex;align-items:flex-end"><button type="submit">Set host</button></div>'
                f'</div></form></div>')
        else:
            # Track: one form, one Save meet setup button (schools + host + scoring/limit/lanes)
            setup_card = (
                '<div class="card"><h2>Meet setup</h2>'
                f'<form method="post" action="/meets/{mid}/track-setup">'
                f'<label>Schools at this meet</label>'
                f'<div class="card" style="background:var(--panel2)">{boxes}</div>'
                f'<label style="margin-top:.8rem">{host_label}</label>'
                f'<select name="host_school_id" style="max-width:300px">{hopts}</select>'
                f'{_sport.settings_fields(m, True)}'
                f'<button type="submit" style="margin-top:1rem">💾 Save meet setup</button>'
                f'</form></div>')
    else:
        pills = ("".join(f'<span class="pill">{escape(s["name"])}</span> ' for s in att) or
                 '<span class="muted">None</span>')
        summary = f'<p class="muted">Host: {escape(host["name"]) if host else "—"}</p>'
        if not is_xc:
            summary += _sport.settings_fields(m, False)
        setup_card = f'<div class="card"><h2>Schools at this meet</h2>{pills}{summary}</div>'

    qr_block = ""
    if m["timer_token"]:
        qr_block = (f'<p><a href="{base}/t/{m["timer_token"]}">{base}/t/{m["timer_token"]}</a></p>'
                    f'<img src="/meets/{mid}/timer-qr.png" width="160" height="160" '
                    f'style="background:#fff;padding:8px;border-radius:8px">')
    if setup:
        qr_block += (f'<form method="post" action="/meets/{mid}/timer-qr">'
                     f'<button class="ghost" type="submit" style="margin-top:.6rem">'
                     f'{"Rotate" if m["timer_token"] else "Generate"} timer QR</button></form>')

    section = _sport.setup_section(m, setup)
    tabs = (_sport._xc_tabs(mid, "setup", road=(m["sport"] == "road"), organizer=is_org) if is_xc
            else _sport._track_tabs(mid, "setup"))
    # Community road events have no schools/host — show only the road setup section.
    if is_org:
        mid_block = section
    else:
        # XC: heats above the schools card; track keeps its meet-setup form first.
        mid_block = f"{section}\n{setup_card}" if is_xc else f"{setup_card}\n{section}"

    edit_card = ""
    if setup:
        pn = m["public_names"] if "public_names" in m.keys() else None

        def _o(v, lbl):
            sel = " selected" if (pn == v or (v == "full" and not pn)) else ""
            return f'<option value="{v}"{sel}>{lbl}</option>'
        name_opts = (_o("full", "Full name")
                     + _o("initials", "Initial . last (e.g. r.rohd)")
                     + _o("bib", "Bib number only"))
        edit_card = (
            f'<details style="margin:.2rem 0 .8rem"><summary class="muted" style="cursor:pointer">'
            f'✏️ Rename meet / date / public results</summary>'
            f'<form method="post" action="/meets/{mid}/edit" class="row" '
            f'style="gap:.6rem;flex-wrap:wrap;margin-top:.5rem">'
            f'<div><label>Name</label><input name="name" value="{escape(m["name"])}"></div>'
            f'<div style="max-width:180px"><label>Date</label>'
            f'<input name="date" type="date" value="{escape(m["date"] or "")}"></div>'
            f'<div style="max-width:230px"><label>Public results show</label>'
            f'<select name="public_names">{name_opts}</select></div>'
            f'<div style="display:flex;align-items:flex-end"><button type="submit">Save</button></div>'
            f'</form></details>')
    sport_label = {"xc": "🏃 Cross-country", "road": "🛣 Road race",
                   "track": "🎽 Track & Field"}.get(m["sport"], "")
    back_link = "/events" if is_org else "/meets"
    back_label = "← Events" if is_org else "← Meets"
    sub = f'{sport_label} · {escape(m["date"] or "")}'
    if not is_org:
        sub += f' · host: {escape(host["name"]) if host else "—"}'
    body = f"""
<p class="muted"><a href="{back_link}">{back_label}</a></p>
<h1>{escape(m['name'])}</h1>
<p class="sub">{sub}</p>
{edit_card}
{tabs}
{print_bar}
{mid_block}
<div class="card"><h2>No-login timer QR</h2>
<p class="muted">Share this QR/link with helpers — it opens the phone timing app for
<b>this meet only</b>, no login, anytime. Rotate to revoke.</p>
{qr_block}</div>
"""
    return shell(g.principal, body, active=("events" if is_org else "meets"),
                 active_district=active_district_id(), districts=_districts_for_switcher())


@bp.get("/results")
def public_directory():
    """Public, no-login directory of meets — parents can find results without a QR."""
    conn = db.connect()
    rows = conn.execute(
        "SELECT m.name, m.date, m.sport, m.public_token, d.name AS dname "
        "FROM meets m JOIN districts d ON d.id=m.district_id "
        "WHERE m.public_token IS NOT NULL ORDER BY d.name, m.date DESC, m.id DESC").fetchall()
    conn.close()
    groups, order = {}, []
    for r in rows:
        if r["dname"] not in groups:
            groups[r["dname"]] = []
            order.append(r["dname"])
        icon = {"xc": "🏃", "track": "🎽", "road": "🛣"}.get(r["sport"], "🎽")
        groups[r["dname"]].append(
            f'<a class="mrow" href="/r/{r["public_token"]}"><span>{icon} {escape(r["name"])}</span>'
            f'<span class="md">{escape(r["date"] or "")}</span></a>')
    secs = "".join(f'<div class="sec"><h2>{escape(d)}</h2>{"".join(groups[d])}</div>'
                   for d in order) or '<p class="mut">No meets published yet.</p>'
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Meet results · XCTimer</title><style>
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:#eef1f5;color:#1b2b3a}}
.top{{background:#12385f;color:#fff;padding:1rem 1.2rem;font-size:1.3rem;font-weight:800}}
main{{max-width:640px;margin:0 auto;padding:1rem 1rem 3rem}}
.sec{{background:#fff;border:1px solid #d9e0e8;border-radius:12px;overflow:hidden;margin:0 0 1.1rem}}
.sec h2{{background:#12385f;color:#fff;margin:0;padding:.6rem 1rem;font-size:1rem}}
.mrow{{display:flex;justify-content:space-between;gap:1rem;padding:.7rem 1rem;color:#1b2b3a;
text-decoration:none;border-top:1px solid #edf1f5;font-weight:600}}
.mrow:hover{{background:#f4f7fa}}
.md{{color:#7c8b9a;font-weight:400;white-space:nowrap}}
.mut{{color:#7c8b9a;text-align:center;padding:2rem}}
</style></head><body>
<div class="top">XCTimer — Meet results</div>
<main>{secs}</main></body></html>"""


@bp.post("/meets/<int:mid>/edit")
@login_required
def edit_meet(mid):
    """Rename a meet / fix its date — without delete-and-recreate."""
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    name = (request.form.get("name") or "").strip()
    date = (request.form.get("date") or "").strip()
    conn = db.connect()
    if name:
        conn.execute("UPDATE meets SET name=? WHERE id=?", (name, mid))
    if date:
        conn.execute("UPDATE meets SET date=? WHERE id=?", (date, mid))
    pn = (request.form.get("public_names") or "").strip()
    if pn in ("full", "initials", "bib"):
        conn.execute("UPDATE meets SET public_names=? WHERE id=?", (pn, mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


@bp.post("/meets/<int:mid>/scoring")
@login_required
def set_scoring(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    ts = 1 if request.form.get("team_scoring") else 0
    conn = db.connect()
    conn.execute("UPDATE meets SET team_scoring=? WHERE id=?", (ts, mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


@bp.post("/meets/<int:mid>/host")
@login_required
def set_host(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    h = (request.form.get("host_school_id") or "").strip()
    host = int(h) if h.isdigit() else None
    if host is not None:
        conn = db.connect()
        ok = conn.execute("SELECT 1 FROM schools WHERE id=? AND district_id=?",
                          (host, m["district_id"])).fetchone()
        conn.close()
        if not ok:
            host = None
    conn = db.connect()
    conn.execute("UPDATE meets SET host_school_id=? WHERE id=?", (host, mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


def _attending_groups(mid):
    conn = db.connect()
    schools = conn.execute(
        "SELECT s.* FROM schools s JOIN meet_schools ms ON ms.school_id=s.id "
        "WHERE ms.meet_id=? ORDER BY s.name", (mid,)).fetchall()
    groups = []
    for s in schools:
        ath = conn.execute("SELECT bib,name,grade,gender FROM athletes WHERE school_id=? "
                           "ORDER BY bib IS NULL, bib, name", (s["id"],)).fetchall()
        groups.append((s["name"], [dict(a) for a in ath]))
    conn.close()
    return groups


def _sticker_groups(mid, with_events, fill_to=0, only_sid=None):
    """[(school_name, logo_path, [athlete dicts])]. For track, attach each
    athlete's events (name + heat/lane) and include only entered athletes.
    fill_to = labels per sheet: pad each school's last sheet with blank stickers
    on the next open bibs (for last-minute adds). only_sid = one school's packet."""
    conn = db.connect()
    schools = conn.execute(
        "SELECT s.id, s.name, s.logo_path, s.bib_start, s.bib_end FROM schools s "
        "JOIN meet_schools ms ON ms.school_id=s.id WHERE ms.meet_id=? ORDER BY s.name", (mid,)).fetchall()
    if only_sid is not None:
        schools = [s for s in schools if s["id"] == only_sid]
    groups = []
    for s in schools:
        ath = conn.execute("SELECT id, bib, name, grade, gender FROM athletes WHERE school_id=? "
                           "ORDER BY bib IS NULL, bib, name", (s["id"],)).fetchall()
        arr = []
        for a in ath:
            d = dict(a)
            if with_events:
                evs = conn.execute(
                    "SELECT e.name AS ename, en.heat, en.lane FROM entries en "
                    "JOIN meet_events me ON me.id=en.meet_event_id JOIN events e ON e.id=me.event_id "
                    "WHERE me.meet_id=? AND en.runner_id=? ORDER BY e.sort", (mid, a["id"])).fetchall()
                ev_list = []
                for ev in evs:
                    if ev["heat"] and ev["lane"]:
                        detail = f" · Sec {ev['heat']} Pos {ev['lane']}"
                    elif ev["heat"]:
                        detail = f" · Sec {ev['heat']}"
                    else:
                        detail = ""
                    ev_list.append(ev["ename"] + detail)
                # Relays store member names (not runner_id) — add any this athlete is on.
                for r in conn.execute(
                        "SELECT e.name AS ename, en.members_json FROM entries en "
                        "JOIN meet_events me ON me.id=en.meet_event_id JOIN events e ON e.id=me.event_id "
                        "WHERE me.meet_id=? AND e.kind='relay' ORDER BY e.sort", (mid,)).fetchall():
                    try:
                        members = json.loads(r["members_json"] or "[]")
                    except (ValueError, TypeError):
                        members = []
                    if a["name"] in members:
                        ev_list.append(f"{r['ename']} · relay")
                if not ev_list:
                    continue  # track: sticker only for entered athletes
                d["events"] = ev_list
            arr.append(d)
        if fill_to:
            real = [a for a in arr if a["bib"] is not None]
            need = (fill_to - len(real) % fill_to) % fill_to
            arr += pdfs.blank_fillers([a["bib"] for a in real],
                                      s["bib_start"], s["bib_end"], need)
        groups.append((s["name"], s["logo_path"], arr))
    conn.close()
    return groups


@bp.get("/meets/<int:mid>/stickers.pdf")
@login_required
def meet_stickers(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    template = request.args.get("template", "5160")
    if m["sport"] == "track":     # track stickers carry events — 5160 is too small
        template = "5163"
    groups = _sticker_groups(mid, with_events=(m["sport"] == "track"),
                             fill_to=pdfs.per_page(template))
    # QR encodes just the bib number (no URL).
    pdf = pdfs.meet_stickers_pdf(groups, template=template, qr_prefix="")
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="meet-stickers.pdf"'})


@bp.get("/meets/<int:mid>/biblist.pdf")
@login_required
def meet_biblist(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    if m["sport"] == "track":  # include each athlete's events — the day-of checklist
        groups = [(nm, arr) for nm, _logo, arr in _sticker_groups(mid, with_events=True)]
    else:
        groups = _attending_groups(mid)
    # Cover page: host-school logo, welcome + instructions, QR to the public results.
    import os as _os
    base = _os.environ.get("XC_PUBLIC_URL") or request.host_url.rstrip("/")
    results_url = f"{base}/r/{m['public_token']}" if m["public_token"] else None
    logo_path = None
    if m["host_school_id"]:
        conn = db.connect()
        hs = conn.execute("SELECT logo_path FROM schools WHERE id=?",
                          (m["host_school_id"],)).fetchone()
        conn.close()
        logo_path = hs["logo_path"] if hs else None
    cover = {"meet_name": m["name"], "logo_path": logo_path, "results_url": results_url,
             "sport": m["sport"]}
    pdf = pdfs.meet_biblist_pdf(f'{m["name"]} — bib lists', groups, cover=cover)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="meet-biblist.pdf"'})


@bp.get("/meets/<int:mid>/school/<int:sid>/stickers.pdf")
@login_required
def school_meet_stickers(mid, sid):
    """One school's meet packet: just their stickers (with events), padded with blanks."""
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    template = request.args.get("template", "5160")
    if m["sport"] == "track":     # track stickers carry events — 5160 is too small
        template = "5163"
    groups = _sticker_groups(mid, with_events=(m["sport"] == "track"),
                             fill_to=pdfs.per_page(template), only_sid=sid)
    pdf = pdfs.meet_stickers_pdf(groups, template=template, qr_prefix="")
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="school-stickers.pdf"'})


@bp.get("/meets/<int:mid>/school/<int:sid>/biblist.pdf")
@login_required
def school_meet_biblist(mid, sid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    if m["sport"] == "track":
        groups = [(nm, arr) for nm, _logo, arr in
                  _sticker_groups(mid, with_events=True, only_sid=sid)]
    else:
        groups = [(nm, arr) for nm, arr in _attending_groups(mid)]
        conn = db.connect()
        srow = conn.execute("SELECT name FROM schools WHERE id=?", (sid,)).fetchone()
        conn.close()
        groups = [g for g in groups if srow and g[0] == srow["name"]]
    pdf = pdfs.meet_biblist_pdf(f'{m["name"]} — bib list', groups)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="school-biblist.pdf"'})
