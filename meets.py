"""Meets: CRUD, attending schools, host, public token, meet-day QR (handoff §8).

A meet has a sport ('xc'|'track'). Phase 3 wires the XC engine (xc.py); track
is Phase 4. Access:
  - view:   super | district_admin(own) | coach attending
  - setup:  super | district_admin(own) | coach who hosts
  - record: super | district_admin(own) | coach attending | meet-QR principal
"""
import io
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


def can_view_meet(m):
    p = g.principal
    if not p:
        return False
    if p.meet_scope:
        return p.meet_scope == m["id"]
    if p.is_super:
        return True
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
            "ORDER BY m.date DESC, m.name").fetchall()
    else:
        rows = conn.execute(
            "SELECT m.*, NULL AS dname FROM meets m WHERE m.district_id=? ORDER BY m.date DESC, m.name",
            (did,)).fetchall()
    conn.close()
    rows = [m for m in rows if can_view_meet(m)]

    show_d = p.is_super and did is None
    trs = []
    for m in rows:
        sport = "🏃 XC" if m["sport"] == "xc" else "🏟️ Track"
        dcol = f'<td>{escape(m["dname"])}</td>' if show_d else ""
        trs.append(f'<tr><td><b><a href="/meets/{m["id"]}">{escape(m["name"])}</a></b></td>'
                   f'<td>{sport}</td><td>{escape(m["date"] or "")}</td>{dcol}</tr>')
    hdr = f'<tr><th>Meet</th><th>Sport</th><th>Date</th>{"<th>District</th>" if show_d else ""}</tr>'
    table = (f'<div class="card"><table>{hdr}{"".join(trs)}</table></div>'
             if rows else '<div class="card muted">No meets yet.</div>')

    form = ""
    can_create = p.is_admin or p.role == "coach"
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
      <option value="track">Track &amp; Field</option></select></div>
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
    body = (f"<h1>Meets</h1><p class='sub'>Cross-country &amp; track meets.</p>"
            f"{_install_card()}{table}{form}")
    return shell(p, body, active="meets", active_district=did, districts=_districts_for_switcher())


@bp.post("/meets")
@login_required
def create_meet():
    p = g.principal
    did = active_district_id()
    if did is None:
        abort(400)
    if not (p.is_admin or p.role == "coach"):
        abort(403)
    name = (request.form.get("name") or "").strip()
    sport = request.form.get("sport") if request.form.get("sport") in ("xc", "track") else "xc"
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
    # coach can only create meets hosted by one of their schools
    if p.role == "coach" and (host is None or host not in p.school_ids()):
        conn.close()
        abort(403)
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
    else:
        pt = conn.execute("SELECT id FROM points_tables WHERE name=?",
                          ("Invitational 10-8-6-4-2-1",)).fetchone()
        if pt:
            conn.execute("UPDATE meets SET points_table_id=? WHERE id=?", (pt[0], mid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


@bp.post("/meets/<int:mid>/delete")
@login_required
def delete_meet(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    conn = db.connect()
    conn.execute("DELETE FROM finishers WHERE race_id IN (SELECT id FROM races WHERE meet_id=?)", (mid,))
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
    is_xc = m["sport"] == "xc"
    results_url = f"/meets/{mid}/results" if is_xc else f"/meets/{mid}/track-results"

    actions = [f'<a class="btn" href="{results_url}">📊 Results</a>',
               f'<a class="btn ghost" href="/r/{m["public_token"]}" target="_blank">Public ↗</a>']
    xlsx_url = f"/meets/{mid}/results.xlsx" if is_xc else f"/meets/{mid}/track-results.xlsx"
    actions.append(f'<a class="btn ghost" href="{xlsx_url}">Export xlsx</a>')

    hs = (f' <a class="btn ghost" href="/meets/{mid}/heatsheets.pdf">Heat sheets</a>'
          if not is_xc else "")
    print_bar = (
        f'<div class="card"><b>Print — all attending schools:</b> '
        f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5160">Stickers 5160</a> '
        f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5163">Stickers 5163</a> '
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
    tabs = "" if is_xc else _sport._track_tabs(mid, "setup")

    body = f"""
<p class="muted"><a href="/meets">← Meets</a></p>
<h1>{escape(m['name'])}</h1>
<p class="sub">{"🏃 Cross-country" if is_xc else "🏟️ Track & Field"} · {escape(m['date'] or '')}
 · host: {escape(host['name']) if host else '—'}</p>
{tabs}
<div class="row">{''.join(actions)}</div>
{print_bar}
{setup_card}
{section}
<div class="card"><h2>No-login timer QR</h2>
<p class="muted">Share this QR/link with helpers — it opens the phone timing app for
<b>this meet only</b>, no login, anytime. Rotate to revoke.</p>
{qr_block}</div>
"""
    return shell(g.principal, body, active="meets",
                 active_district=active_district_id(), districts=_districts_for_switcher())


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


def _sticker_groups(mid, with_events):
    """[(school_name, logo_path, [athlete dicts])]. For track, attach each
    athlete's events (name + heat/lane) and include only entered athletes."""
    conn = db.connect()
    schools = conn.execute(
        "SELECT s.id, s.name, s.logo_path FROM schools s JOIN meet_schools ms ON ms.school_id=s.id "
        "WHERE ms.meet_id=? ORDER BY s.name", (mid,)).fetchall()
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
                if not evs:
                    continue  # track: sticker only for entered athletes
                d["events"] = [
                    ev["ename"] + (f" · H{ev['heat']} L{ev['lane']}" if ev["heat"] and ev["lane"]
                                   else (f" · Sec {ev['heat']}" if ev["heat"] else ""))
                    for ev in evs]
            arr.append(d)
        groups.append((s["name"], s["logo_path"], arr))
    conn.close()
    return groups


@bp.get("/meets/<int:mid>/stickers.pdf")
@login_required
def meet_stickers(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    prefix = f'{os.environ.get("XC_PUBLIC_URL", "")}/bibcheck?bib='
    groups = _sticker_groups(mid, with_events=(m["sport"] == "track"))
    pdf = pdfs.meet_stickers_pdf(groups,
                                 template=request.args.get("template", "5160"), qr_prefix=prefix)
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="meet-stickers.pdf"'})


@bp.get("/meets/<int:mid>/biblist.pdf")
@login_required
def meet_biblist(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    pdf = pdfs.meet_biblist_pdf(f'{m["name"]} — bib lists', _attending_groups(mid))
    return Response(pdf, mimetype="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="meet-biblist.pdf"'})
