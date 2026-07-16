"""Dashboard + district and user management (handoff §2, §4) — Phase 1.

Districts: super admin only. Users: super admin (any district) and district admin
(own district). Every write is district-scoped server-side.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_MT = ZoneInfo("America/Denver")   # Mountain Time (handles MST/MDT)

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, jsonify, Response

from . import db, audit
from .auth import (login_required, role_required, create_user, issue_reset_token,
                   send_setup_email, hash_password, ROLES)
from .tenancy import active_district_id, require_district, all_districts
from .ui import shell

bp = Blueprint("admin", __name__)


def _districts_for_switcher():
    return all_districts() if g.principal.is_super else None


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return s or "district"


# ------------------------------- dashboard -------------------------------
@bp.get("/dashboard")
@login_required
def dashboard():
    p = g.principal
    did = active_district_id()

    # Only super / district admins have an admin dashboard — everyone else goes home
    # (coaches/timers -> Meets, race directors -> Events).
    if not p.is_admin:
        from .ui import home_url
        return redirect(home_url(p))

    # Meet-day QR principal: minimal scoped landing (recording UI = Phase 3/4).
    if p.meet_scope:
        conn = db.connect()
        meet = conn.execute("SELECT * FROM meets WHERE id=?", (p.meet_scope,)).fetchone()
        conn.close()
        body = (
            f"<h1>Meet-day timer</h1>"
            f"<div class='card'><p>You're signed in for "
            f"<b>{escape(meet['name']) if meet else 'this meet'}</b> (today only, no login).</p>"
            f"<p class='muted'>The recording console arrives with the "
            f"{'XC' if meet and meet['sport']=='xc' else 'track'} engine. "
            f"This confirms the meet-scoped session works.</p></div>"
        )
        return shell(p, body, active="dashboard")

    conn = db.connect()
    if p.is_super and did is None:
        stats = {
            "Districts": conn.execute("SELECT COUNT(*) FROM districts").fetchone()[0],
            "Schools": conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0],
            "Users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "Meets": conn.execute("SELECT COUNT(*) FROM meets").fetchone()[0],
        }
        scope_note = "All districts"
    else:
        stats = {
            "Schools": conn.execute(
                "SELECT COUNT(*) FROM schools WHERE district_id=?", (did,)).fetchone()[0],
            "Users": conn.execute(
                "SELECT COUNT(*) FROM users WHERE district_id=?", (did,)).fetchone()[0],
            "Meets": conn.execute(
                "SELECT COUNT(*) FROM meets WHERE district_id=?", (did,)).fetchone()[0],
        }
        d = conn.execute("SELECT name FROM districts WHERE id=?", (did,)).fetchone()
        scope_note = d["name"] if d else "—"
    # District-admin branding: upload/replace their district logo (shown top-left).
    branding = ""
    if p.role == "district_admin" and p.district_id:
        drow = conn.execute("SELECT name, logo_path FROM districts WHERE id=?",
                            (p.district_id,)).fetchone()
        thumb = (f'<img src="{escape(drow["logo_path"])}" style="height:34px;background:#fff;'
                 f'border-radius:6px;padding:3px;vertical-align:middle;margin-right:.6rem"> '
                 if drow and drow["logo_path"] else '')
        branding = (
            f'<div class="card"><h2>District branding</h2>'
            f'<p class="muted">Your district logo appears in the top-left header.</p>'
            f'{thumb}<form class="inline" method="post" action="/districts/{p.district_id}/logo" '
            f'enctype="multipart/form-data"><input type="file" name="logo" accept="image/*"> '
            f'<button type="submit">Upload logo</button></form></div>')
    conn.close()

    cards = "".join(
        f'<div class="card" style="flex:1;text-align:center">'
        f'<div style="font-size:2rem;font-weight:700">{v}</div>'
        f'<div class="muted">{escape(k)}</div></div>'
        for k, v in stats.items()
    )
    from .waivers import dashboard_card as _waiver_card
    body = (
        f"<h1>Dashboard</h1><p class='sub'>Signed in as "
        f"<b>{escape(p.name or p.email)}</b> · {escape(scope_note)}</p>"
        f'<div class="row">{cards}</div>{branding}{_waiver_card(p)}'
    )
    return shell(p, body, active="dashboard",
                 active_district=did, districts=_districts_for_switcher())


# ------------------------------- districts -------------------------------
@bp.get("/districts")
@role_required("super_admin")
def list_districts():
    rows = all_districts()
    conn = db.connect()
    counts = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT d.id, "
        "(SELECT COUNT(*) FROM schools s WHERE s.district_id=d.id), "
        "(SELECT COUNT(*) FROM users u WHERE u.district_id=d.id) "
        "FROM districts d").fetchall()}
    conn.close()

    body_rows = []
    for d in rows:
        sc, us = counts.get(d["id"], (0, 0))
        try:
            masked = bool(json.loads(d["settings_json"] or "{}").get("mask_public"))
        except (ValueError, TypeError):
            masked = False
        mask_btn = (f'<form class="inline" method="post" action="/districts/{d["id"]}/mask">'
                    f'<button class="{"btn" if masked else "ghost"}" type="submit">'
                    f'{"Masked" if masked else "Full names"}</button></form>')
        try:
            road_on = bool(json.loads(d["settings_json"] or "{}").get("road_enabled"))
        except (ValueError, TypeError):
            road_on = False
        road_btn = (f'<form class="inline" method="post" action="/districts/{d["id"]}/road">'
                    f'<button class="{"btn" if road_on else "ghost"}" type="submit">'
                    f'{"🛣 On" if road_on else "Off"}</button></form>')
        thumb = (f'<img src="{escape(d["logo_path"])}" style="height:26px;background:#fff;'
                 f'border-radius:5px;padding:2px;vertical-align:middle;margin-right:.4rem"> '
                 if d["logo_path"] else '')
        logo_cell = (f'{thumb}<form class="inline" method="post" action="/districts/{d["id"]}/logo" '
                     f'enctype="multipart/form-data"><input type="file" name="logo" accept="image/*" '
                     f'style="width:140px;font-size:.72rem"> <button class="ghost" type="submit">Set</button></form>')
        body_rows.append(
            f'<tr><td><b>{escape(d["name"])}</b><br>'
            f'<span class="muted">{escape(d["slug"])}</span></td>'
            f'<td>{logo_cell}</td>'
            f'<td>{sc} schools</td><td>{us} users</td>'
            f'<td>{mask_btn}</td>'
            f'<td>{road_btn}</td>'
            f'<td style="text-align:right">'
            f'<form class="inline" method="post" action="/districts/{d["id"]}/delete" '
            f'onsubmit="return confirm(\'Delete {escape(d["name"])} and ALL its data?\')">'
            f'<button class="danger" type="submit">Delete</button></form></td></tr>'
        )
    table = (f'<div class="card"><table><tr><th>District</th><th>Logo</th><th>Schools</th>'
             f'<th>Users</th><th>Public results</th><th>Road races</th><th></th></tr>'
             f'{"".join(body_rows)}</table></div>'
             if rows else '<div class="card muted">No districts yet.</div>')

    form = """
<div class="card"><h2>Add a district</h2>
<form method="post" action="/districts">
  <label>Name</label><input name="name" placeholder="Alpine School District" required>
  <button type="submit" style="margin-top:1rem">Create district</button>
</form></div>
<div class="card"><h2>Demo data</h2>
<p class="muted">Create a self-contained “Demo District” with rosters and a finished
meet — handy for showcasing without touching real data.</p>
<form method="post" action="/seed-demo"><button class="ghost" type="submit">Seed demo district</button></form>
</div>"""
    body = f"<h1>Districts</h1><p class='sub'>Top-level tenants. Super Admin only.</p>{table}{form}"
    return shell(g.principal, body, active="districts",
                 active_district=active_district_id(), districts=all_districts())


@bp.post("/districts")
@role_required("super_admin")
def create_district():
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    slug = _slugify(name)
    conn = db.connect()
    # Ensure slug uniqueness.
    base, n = slug, 2
    while conn.execute("SELECT 1 FROM districts WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    conn.execute("INSERT INTO districts (name, slug) VALUES (?,?)", (name, slug))
    conn.commit()
    conn.close()
    return redirect("/districts")


@bp.post("/seed-demo")
@role_required("super_admin")
def seed_demo():
    from . import demo_seed
    demo_seed.seed()
    return redirect("/districts")


@bp.post("/districts/<int:did>/mask")
@role_required("super_admin")
def toggle_mask(did):
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    if not d:
        conn.close(); abort(404)
    settings = json.loads(d["settings_json"] or "{}")
    settings["mask_public"] = not settings.get("mask_public")
    conn.execute("UPDATE districts SET settings_json=? WHERE id=?", (json.dumps(settings), did))
    conn.commit()
    conn.close()
    return redirect("/districts")


@bp.post("/districts/<int:did>/road")
@role_required("super_admin")
def toggle_road(did):
    """Enable/disable the Road-race sport for this district (super admin only)."""
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    if not d:
        conn.close()
        abort(404)
    settings = json.loads(d["settings_json"] or "{}")
    settings["road_enabled"] = not settings.get("road_enabled")
    conn.execute("UPDATE districts SET settings_json=? WHERE id=?", (json.dumps(settings), did))
    conn.commit()
    conn.close()
    return redirect("/districts")


@bp.post("/districts/<int:did>/logo")
@login_required
def district_logo(did):
    """Set a district's logo. Super admin (any) or the district's own admin."""
    p = g.principal
    if not (p.is_super or (p.role == "district_admin" and p.district_id == did)):
        abort(403)
    from .schools import _save_logo
    conn = db.connect()
    d = conn.execute("SELECT name FROM districts WHERE id=?", (did,)).fetchone()
    conn.close()
    if not d:
        abort(404)
    lp = _save_logo(request.files.get("logo"), f"district-{d['name']}")
    if lp:
        conn = db.connect()
        conn.execute("UPDATE districts SET logo_path=? WHERE id=?", (lp, did))
        conn.commit()
        conn.close()
    return redirect(request.referrer or "/districts")


@bp.post("/districts/<int:did>/delete")
@role_required("super_admin")
def delete_district(did):
    conn = db.connect()
    try:
        if not conn.execute("SELECT 1 FROM districts WHERE id=?", (did,)).fetchone():
            abort(404)
        # Full FK-safe cascade, leaves-first (outage postmortem: the old version
        # deleted parents with live children — users with sessions, schools with
        # athletes, meets with races/entries — and crashed on real data).
        in_meets = "(SELECT id FROM meets WHERE district_id=?)"
        in_mes = ("(SELECT me.id FROM meet_events me JOIN meets m ON m.id=me.meet_id "
                  "WHERE m.district_id=?)")
        in_schools = "(SELECT id FROM schools WHERE district_id=?)"
        in_users = "(SELECT id FROM users WHERE district_id=?)"
        # meet subtree: results -> entries -> meet_events; finishers -> races
        conn.execute(f"DELETE FROM results WHERE entry_id IN "
                     f"(SELECT id FROM entries WHERE meet_event_id IN {in_mes})", (did,))
        conn.execute(f"DELETE FROM track_taps WHERE meet_event_id IN {in_mes}", (did,))
        conn.execute(f"DELETE FROM track_clocks WHERE meet_event_id IN {in_mes}", (did,))
        conn.execute(f"DELETE FROM entries WHERE meet_event_id IN {in_mes}", (did,))
        conn.execute(f"DELETE FROM meet_events WHERE meet_id IN {in_meets}", (did,))
        conn.execute(f"DELETE FROM finishers WHERE race_id IN "
                     f"(SELECT id FROM races WHERE meet_id IN {in_meets})", (did,))
        conn.execute(f"DELETE FROM races WHERE meet_id IN {in_meets}", (did,))
        conn.execute(f"DELETE FROM meet_schools WHERE meet_id IN {in_meets}", (did,))
        conn.execute("DELETE FROM meets WHERE district_id=?", (did,))
        # athlete subtree
        conn.execute(f"DELETE FROM athlete_waivers WHERE athlete_id IN "
                     f"(SELECT id FROM athletes WHERE school_id IN {in_schools})", (did,))
        conn.execute(f"DELETE FROM athletes WHERE school_id IN {in_schools}", (did,))
        # user subtree (sessions/MFA reference users)
        conn.execute(f"DELETE FROM sessions WHERE user_id IN {in_users}", (did,))
        conn.execute(f"DELETE FROM mfa_challenges WHERE user_id IN {in_users}", (did,))
        conn.execute(f"DELETE FROM mfa_devices WHERE user_id IN {in_users}", (did,))
        conn.execute(f"DELETE FROM user_schools WHERE school_id IN {in_schools}", (did,))
        conn.execute(f"DELETE FROM user_schools WHERE user_id IN {in_users}", (did,))
        conn.execute("DELETE FROM users WHERE district_id=?", (did,))
        # district-level leaves, then the district itself
        conn.execute("DELETE FROM waiver_templates WHERE district_id=?", (did,))
        conn.execute("DELETE FROM district_records WHERE district_id=?", (did,))
        conn.execute("DELETE FROM schools WHERE district_id=?", (did,))
        conn.execute("DELETE FROM districts WHERE id=?", (did,))
        conn.commit()
    finally:
        conn.close()
    return redirect("/districts")


# --------------------------------- users ---------------------------------
def _creatable_roles(principal):
    if principal.is_super:
        return ["district_admin", "coach", "timer"]
    return ["coach", "timer"]  # district_admin


@bp.get("/users")
@role_required("super_admin", "district_admin")
def list_users():
    p = g.principal
    did = active_district_id()
    conn = db.connect()
    if p.is_super and did is None:
        rows = conn.execute(
            "SELECT u.*, d.name AS dname FROM users u "
            "LEFT JOIN districts d ON d.id=u.district_id ORDER BY u.role, u.email"
        ).fetchall()
    elif p.is_super:
        # District selected: that district's users PLUS the global super admins,
        # so a super always sees their own account and platform peers.
        rows = conn.execute(
            "SELECT u.*, d.name AS dname FROM users u "
            "LEFT JOIN districts d ON d.id=u.district_id "
            "WHERE u.district_id=? OR u.role='super_admin' ORDER BY u.role, u.email",
            (did,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT u.*, NULL AS dname FROM users u WHERE u.district_id=? ORDER BY u.role, u.email",
            (did,),
        ).fetchall()
    schools = conn.execute(
        "SELECT * FROM schools WHERE district_id=? ORDER BY name", (did,)
    ).fetchall() if did is not None else []
    conn.close()

    show_d = p.is_super and did is None
    hdr = ("<tr><th>User</th><th>Role</th>" + ("<th>District</th>" if show_d else "")
           + "<th>Status</th><th>Last login</th><th>MFA</th><th></th></tr>")

    def _fmt_login(iso):
        if not iso:
            return '<span class="muted">never</span>'
        try:
            dt = datetime.fromisoformat(str(iso))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dt = dt.astimezone(_MT)
            return f'<span class="muted">{escape(dt.strftime("%b %-d, %-I:%M %p %Z"))}</span>'
        except Exception:  # noqa: BLE001
            return f'<span class="muted">{escape(str(iso)[:16])}</span>'
    trs = []
    for u in rows:
        status = ('<span class="muted">pending setup</span>' if not u["password_hash"]
                  else "active")
        if "is_demo" in u.keys() and u["is_demo"]:
            status += ' <span class="pill">demo</span>'
        dcol = f'<td>{escape(u["dname"] or "—")}</td>' if show_d else ""
        # Pending users get a fresh setup invite; active users get a login/reset link.
        resend_label = "Resend invite" if not u["password_hash"] else "Send login link"
        resend = (f'<form class="inline" method="post" action="/users/{u["id"]}/resend">'
                  f'<button class="ghost" type="submit">{resend_label}</button></form> ')
        # Demo accounts are shareable showcase logins — let an admin set a known password.
        if "is_demo" in u.keys() and u["is_demo"]:
            resend += (
                f'<form class="inline" method="post" action="/users/{u["id"]}/demo-password">'
                f'<input name="password" placeholder="demo password" required '
                f'style="width:auto;padding:.35rem .5rem">'
                f'<button class="ghost" type="submit">Set password</button></form> ')
        # Role: editable dropdown when this admin may manage this user's role, else a pill.
        # Never editable for super admins or for your own account (no self-lockout).
        assignable = _creatable_roles(p)
        if u["role"] in assignable and u["role"] != "super_admin" and u["id"] != p.id:
            opts = "".join(
                f'<option value="{r}" {"selected" if r == u["role"] else ""}>'
                f'{r.replace("_", " ").title()}</option>' for r in assignable)
            role_cell = (
                f'<form class="inline" method="post" action="/users/{u["id"]}/role">'
                f'<select name="role" onchange="this.form.submit()" '
                f'style="width:auto;padding:.3rem .5rem">{opts}</select></form>')
        else:
            role_cell = f'<span class="pill">{escape(u["role"].replace("_"," "))}</span>'
        # Per-user MFA opt-in. Toggle persists now; enforcement (email code) ships later.
        mfa_on = "mfa_enabled" in u.keys() and u["mfa_enabled"]
        mfa_cell = (
            f'<form class="inline" method="post" action="/users/{u["id"]}/mfa">'
            f'<input type="hidden" name="on" value="{0 if mfa_on else 1}">'
            f'<button class="ghost" type="submit" '
            f'title="Two-factor sign-in (email code). Enforcement coming soon.">'
            f'{"🔒 On" if mfa_on else "Off"}</button></form>')
        trs.append(
            f'<tr><td><b>{escape(u["name"] or "")}</b><br>'
            f'<span class="muted">{escape(u["email"])}</span></td>'
            f'<td>{role_cell}</td>'
            f'{dcol}<td>{status}</td>'
            f'<td>{_fmt_login(u["last_login"])}</td>'
            f'<td>{mfa_cell}</td>'
            f'<td style="text-align:right">{resend}'
            f'<form class="inline" method="post" action="/users/{u["id"]}/delete" '
            f'onsubmit="return confirm(\'Delete {escape(u["email"])}?\')">'
            f'<button class="danger" type="submit">Delete</button></form></td></tr>'
        )
    table = (f'<div class="card"><table>{hdr}{"".join(trs)}</table></div>'
             if rows else '<div class="card muted">No users yet.</div>')

    # Create form. Super admins pick the target district right in the form (so they
    # don't have to switch the header first); district admins are fixed to their own.
    role_opts = "".join(f'<option value="{r}">{r.replace("_"," ").title()}</option>'
                        for r in _creatable_roles(p))
    if p.is_super:
        ds = all_districts()
        if not ds:
            form = '<p class="muted">Create a district first.</p>'
        else:
            dopts = "".join(
                f'<option value="{d["id"]}" {"selected" if d["id"]==did else ""}>'
                f'{escape(d["name"])}</option>' for d in ds)
            district_block = (f'<label>District</label>'
                              f'<select name="district_id" id="u_dist" required>{dopts}</select>')
            conn = db.connect()
            all_sch = conn.execute(
                "SELECT id, name, district_id FROM schools ORDER BY name").fetchall()
            conn.close()
            school_opts = "".join(
                f'<option value="{s["id"]}" data-d="{s["district_id"]}">{escape(s["name"])}</option>'
                for s in all_sch)
    else:
        district_block = ""
        school_opts = "".join(f'<option value="{s["id"]}">{escape(s["name"])}</option>'
                              for s in schools)

    if not p.is_super or all_districts():
        school_block = (
            f'<label>Schools <span class="muted">— coach/timer scope, hold ⌘/Ctrl to '
            f'multi-select</span></label>'
            f'<select name="school_ids" id="u_schools" multiple size="4">{school_opts}</select>'
            if school_opts else
            '<p class="muted">Add schools first to scope coaches/timers.</p>'
        )
        # Super admin: filter the school list to the chosen district.
        filter_js = ("""
<script>
(function(){
  var d=document.getElementById('u_dist'), sel=document.getElementById('u_schools');
  if(!d||!sel) return;
  function sync(){
    Array.prototype.forEach.call(sel.options,function(o){
      var hide = o.getAttribute('data-d')!==d.value;
      o.hidden=hide; if(hide) o.selected=false;
    });
  }
  d.addEventListener('change',sync); sync();
})();
</script>""" if p.is_super else "")
        form = f"""
<div class="card"><h2>Add a user</h2>
<form method="post" action="/users">
  <div class="row">
    <div><label>Name</label><input name="name"></div>
    <div><label>Email</label><input name="email" type="email" required></div>
  </div>
  {district_block}
  <label>Role</label><select name="role">{role_opts}</select>
  {school_block}
  <label style="display:flex;gap:.5rem;align-items:center;margin-top:.7rem;font-size:.9rem">
    <input type="checkbox" name="is_demo" style="width:auto"> Demo account (read-only, anonymized names)</label>
  <button type="submit" style="margin-top:1rem">Create &amp; send invite</button>
</form>
<p class="muted">An email with a setup link is sent so they can set their password.</p>
</div>{filter_js}"""

    sub = "Coaches, timers, and district admins."
    if p.is_super:
        sub += (' <span class="muted">Showing this district plus super admins — '
                'choose <b>All districts</b> in the header to see every user.</span>'
                if did is not None else
                ' <span class="muted">Showing every user across all districts.</span>')
    body = f"<h1>Users</h1><p class='sub'>{sub}</p>{table}{form}"
    return shell(p, body, active="users", msg=request.args.get("msg"),
                 err=request.args.get("err"),
                 active_district=did, districts=_districts_for_switcher())


@bp.post("/users")
@role_required("super_admin", "district_admin")
def create_user_route():
    p = g.principal
    # Super admins choose the district in the form; district admins are fixed to theirs.
    if p.is_super:
        fd = (request.form.get("district_id") or "").strip()
        did = int(fd) if fd.isdigit() else None
    else:
        did = active_district_id()
    if did is None:
        abort(400)
    require_district(did)
    conn = db.connect()
    exists = conn.execute("SELECT 1 FROM districts WHERE id=?", (did,)).fetchone()
    conn.close()
    if not exists:
        abort(400)
    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("name") or "").strip() or None
    role = (request.form.get("role") or "").strip()
    if role not in _creatable_roles(p) or "@" not in email:
        abort(400)
    school_ids = [int(x) for x in request.form.getlist("school_ids") if x.isdigit()]
    # Only coaches/timers are school-scoped; ignore any schools for admins.
    if role not in ("coach", "timer"):
        school_ids = []
    # Guard: chosen schools must belong to this district.
    if school_ids:
        conn = db.connect()
        ok = conn.execute(
            f"SELECT COUNT(*) FROM schools WHERE district_id=? AND id IN "
            f"({','.join('?' * len(school_ids))})", (did, *school_ids)
        ).fetchone()[0]
        conn.close()
        if ok != len(school_ids):
            abort(400)
    is_demo = bool(request.form.get("is_demo"))
    try:
        _uid, token = create_user(email, role, district_id=did, name=name,
                                  school_ids=school_ids, is_demo=is_demo)
    except Exception:  # duplicate email, etc.
        return redirect("/users")
    send_setup_email(email, token)
    return redirect("/users")


@bp.post("/users/<int:uid>/resend")
@role_required("super_admin", "district_admin")
def resend_invite(uid):
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not u:
        abort(404)
    if u["district_id"] is not None:
        require_district(u["district_id"])
    token = issue_reset_token(uid)
    send_setup_email(u["email"], token, reset=bool(u["password_hash"]))
    return redirect("/users?msg=" + ("Login+link+sent" if u["password_hash"] else "Invite+resent"))


@bp.post("/users/<int:uid>/role")
@role_required("super_admin", "district_admin")
def change_role(uid):
    p = g.principal
    new_role = (request.form.get("role") or "").strip()
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    if not u:
        abort(404)
    if u["district_id"] is not None:
        require_district(u["district_id"])
    # Guards: can't change your own role, can't touch a super admin, and both the
    # old and new role must be ones this admin is allowed to assign.
    allowed = _creatable_roles(p)
    if (u["id"] == p.id or u["role"] == "super_admin"
            or u["role"] not in allowed or new_role not in allowed):
        abort(403)
    if new_role != u["role"]:
        conn = db.connect()
        conn.execute("UPDATE users SET role=? WHERE id=?", (new_role, uid))
        # Dropping to a non-scoped role: clear school assignments (coach/timer only).
        if new_role not in ("coach", "timer"):
            conn.execute("DELETE FROM user_schools WHERE user_id=?", (uid,))
        conn.commit()
        conn.close()
    return redirect("/users?msg=Role+updated")


@bp.post("/users/<int:uid>/mfa")
@role_required("super_admin", "district_admin")
def user_mfa(uid):
    """Toggle a user's MFA opt-in flag. Stored now; login enforcement ships later."""
    on = 1 if (request.form.get("on") == "1") else 0
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        abort(404)
    if u["district_id"] is not None:
        require_district(u["district_id"])   # district admins limited to their own users
    conn.execute("UPDATE users SET mfa_enabled=? WHERE id=?", (on, uid))
    conn.commit()
    conn.close()
    return redirect("/users?msg=MFA+preference+updated")


@bp.post("/users/<int:uid>/demo-password")
@role_required("super_admin", "district_admin")
def set_demo_password(uid):
    from urllib.parse import quote
    pw = (request.form.get("password") or "").strip()
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        abort(404)
    if u["district_id"] is not None:
        require_district(u["district_id"])
    # Only demo accounts get a directly-set (shareable) password.
    if not ("is_demo" in u.keys() and u["is_demo"]):
        conn.close()
        abort(403)
    if len(pw) < 4:
        conn.close()
        return redirect("/users?err=" + quote("Demo password must be at least 4 characters."))
    conn.execute(
        "UPDATE users SET password_hash=?, setup_token=NULL, token_expires=NULL WHERE id=?",
        (hash_password(pw), uid))
    conn.commit()
    conn.close()
    return redirect("/users?msg=" + quote(f"Demo login ready — {u['email']} / {pw}"))


@bp.post("/users/<int:uid>/delete")
@role_required("super_admin", "district_admin")
def delete_user(uid):
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        conn.close()
        abort(404)
    if u["district_id"] is not None:
        require_district(u["district_id"])
    if u["role"] == "super_admin":
        conn.close()
        abort(403)
    conn.execute("DELETE FROM user_schools WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM mfa_challenges WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM mfa_devices WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return redirect("/users")


# ============================ super-admin console ============================
_CONSOLE_RANGES = {"1h": ("1 hour", "1 hour ago"), "24h": ("24 hours", "1 day ago"),
                   "7d": ("7 days", "7 days ago")}


def _ts_mt(ts):
    """A journal ISO timestamp -> readable Mountain Time."""
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_MT).strftime("%b %-d, %-I:%M:%S %p")
    except Exception:  # noqa: BLE001
        return ts[:19].replace("T", " ")


def _line_mt(line):
    """Rewrite a raw journal line's leading timestamp into Mountain Time."""
    parts = line.split(" ", 1)
    try:
        dt = datetime.fromisoformat(parts[0])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        stamp = dt.astimezone(_MT).strftime("%m-%d %H:%M:%S")
        return stamp + (" " + parts[1] if len(parts) > 1 else "")
    except Exception:  # noqa: BLE001
        return line


def _read_journal(since, cap=20000):
    """XCLOG lines from this service's journal since `since` (newest last)."""
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", "xctimer", "--since", since,
             "-o", "short-iso", "--no-pager"],
            capture_output=True, text=True, timeout=12).stdout
    except Exception:  # noqa: BLE001
        return []
    return [ln for ln in out.splitlines() if "XCLOG " in ln][-cap:]


def _parse_journal(lines):
    reqs, logins = [], []
    for ln in lines:
        ts = ln.split(" ", 1)[0]
        parts = ln[ln.find("XCLOG "):].split()
        if len(parts) < 3:
            continue
        if parts[1] == "REQ" and len(parts) >= 6:
            try:
                status = int(parts[3])
            except ValueError:
                continue
            reqs.append({"ts": ts, "ip": parts[2], "status": status,
                         "method": parts[4], "path": parts[5]})
        elif parts[1] == "LOGIN" and len(parts) >= 6:
            logins.append({"ts": ts, "result": parts[2], "email": parts[3],
                           "role": parts[4], "ip": parts[5]})
    return reqs, logins


# ------------------------------- server vitals (Console) -------------------------------
# Live host stats are read locally (load/mem/disk/uptime) — richer and cheaper than the
# Hetzner API, which can't report memory or disk-space-used. Monthly outbound traffic vs.
# the included quota is the one thing worth the API; it activates when a token is present.
_HZ_CACHE = {"exp": 0.0, "data": None}


def _fmt_bytes(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return (f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024


def _fmt_dur(sec):
    sec = int(sec or 0)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, _ = divmod(sec, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def _meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, _, rest = line.partition(":")
            parts = rest.strip().split()
            if parts:
                info[k] = int(parts[0]) * 1024   # kB -> bytes
    return info


def _env_ci(*names):
    """Look up an env var by any of the given names, case-insensitively."""
    want = {n.lower() for n in names}
    for k, v in os.environ.items():
        if k.lower() in want and (v or "").strip():
            return v.strip()
    return None


def _hetzner_traffic():
    """Outbound traffic vs. included quota from the Hetzner Cloud API, cached 5 min.
    Reads a token from HETZNER_API_TOKEN/HETZNER_API_KEY (any case); server id optional."""
    token = _env_ci("HETZNER_API_TOKEN", "HETZNER_API_KEY", "HETZNER_TOKEN")
    if not token:
        return None
    if _HZ_CACHE["exp"] > time.monotonic():
        return _HZ_CACHE["data"]
    hdr = {"Authorization": f"Bearer {token}"}
    data = None
    try:
        sid = _env_ci("HETZNER_SERVER_ID")
        if not sid:
            req = urllib.request.Request("https://api.hetzner.cloud/v1/servers?per_page=1", headers=hdr)
            with urllib.request.urlopen(req, timeout=4) as r:
                servers = json.load(r).get("servers", [])
            if not servers:
                data = {"error": "token has no servers"}
            else:
                sid = servers[0]["id"]
        if data is None:
            req = urllib.request.Request(f"https://api.hetzner.cloud/v1/servers/{sid}", headers=hdr)
            with urllib.request.urlopen(req, timeout=4) as r:
                obj = json.load(r)["server"]
            data = {"out": obj.get("outgoing_traffic") or 0,
                    "included": obj.get("included_traffic") or 0}
    except Exception as e:                                   # network/auth/parse — show, don't crash
        data = {"error": str(e)[:140]}
    _HZ_CACHE["exp"] = time.monotonic() + 300
    _HZ_CACHE["data"] = data
    return data


def _server_stats_display():
    """Formatted host vitals for the Console server card (and its live-refresh feed)."""
    d = {}
    try:
        la = os.getloadavg()
        d["load"] = f"{la[0]:.2f} / {la[1]:.2f} / {la[2]:.2f}"
    except Exception:
        d["load"] = "n/a"
    d["cpus"] = f"{os.cpu_count() or 1} vCPU"
    try:
        mi = _meminfo()
        total, avail = mi.get("MemTotal", 0), mi.get("MemAvailable", 0)
        used = total - avail
        pct = round(used / total * 100) if total else 0
        d["mem"] = f"{_fmt_bytes(used)} / {_fmt_bytes(total)} ({pct}%)"
    except Exception:
        d["mem"] = "n/a"
    try:
        du = shutil.disk_usage("/")
        d["disk"] = f"{_fmt_bytes(du.used)} / {_fmt_bytes(du.total)} ({round(du.used / du.total * 100)}%)"
    except Exception:
        d["disk"] = "n/a"
    try:
        with open("/proc/uptime") as f:
            d["uptime"] = _fmt_dur(float(f.read().split()[0]))
    except Exception:
        d["uptime"] = "n/a"
    hz = _hetzner_traffic()
    if hz is None:
        d["traffic"] = "set HETZNER_API_TOKEN in the env to enable"
    elif "error" in hz:
        d["traffic"] = "⚠ " + hz["error"]
    else:
        inc = hz.get("included") or 0
        pct = (hz["out"] / inc * 100) if inc else 0
        d["traffic"] = f'{_fmt_bytes(hz["out"])} of {_fmt_bytes(inc)} included ({pct:.1f}%)'
    return d


def _server_card():
    d = _server_stats_display()
    try:
        host = os.uname().nodename
    except Exception:
        host = "host"

    def t(lbl, vid, val):
        return (f'<div style="flex:1;min-width:110px;text-align:center;padding:.4rem">'
                f'<div class="muted" style="font-size:.7rem;letter-spacing:.06em">{lbl}</div>'
                f'<div id="{vid}" style="font-size:1.15rem;font-weight:800">{escape(val)}</div></div>')
    return (f'<div class="card"><h2>🖥️ Server <span class="muted">— {escape(host)} · live</span></h2>'
            f'<div style="display:flex;gap:.4rem;flex-wrap:wrap">'
            + t("LOAD 1/5/15m", "srv-load", d["load"])
            + t("CPU", "srv-cpus", d["cpus"])
            + t("MEMORY", "srv-mem", d["mem"])
            + t("DISK", "srv-disk", d["disk"])
            + t("UPTIME", "srv-uptime", d["uptime"])
            + '</div>'
            f'<div class="muted" style="margin-top:.55rem;font-size:.85rem">📡 Outbound traffic this month: '
            f'<span id="srv-traffic">{escape(d["traffic"])}</span></div>'
            '<script>'
            'async function srvStats(){'
            ' try{const d=await (await fetch("/admin/console/stats")).json();'
            ' ["load","cpus","mem","disk","uptime","traffic"].forEach(function(k){'
            ' const el=document.getElementById("srv-"+k); if(el&&d[k]!=null) el.textContent=d[k];});'
            ' }catch(e){}}'
            'setInterval(srvStats,5000);'
            '</script></div>')


@bp.get("/admin/console/stats")
@role_required("super_admin")
def console_stats():
    return jsonify(_server_stats_display())


@bp.get("/admin/console")
@role_required("super_admin")
def console():
    rng = request.args.get("range", "1h")
    label, since = _CONSOLE_RANGES.get(rng, _CONSOLE_RANGES["1h"])
    reqs, logins = _parse_journal(_read_journal(since))

    buckets = {2: 0, 3: 0, 4: 0, 5: 0}
    ips, p404 = {}, {}
    for r in reqs:
        b = r["status"] // 100
        if b in buckets:
            buckets[b] += 1
        d = ips.setdefault(r["ip"], {"n": 0, 2: 0, 3: 0, 4: 0, 5: 0})
        d["n"] += 1
        if b in d:
            d[b] += 1
        if r["status"] == 404:
            pp = p404.setdefault(r["path"], set())
            pp.add(r["ip"])
    total = len(reqs)

    def tab(k, lbl):
        on = "background:var(--acc);color:#04101f;border-color:var(--acc)" if k == rng else ""
        return (f'<a href="/admin/console?range={k}" class="btn ghost" '
                f'style="padding:.4rem 1rem;{on}">{lbl}</a>')
    tabs = tab("1h", "1 hour") + " " + tab("24h", "24 hours") + " " + tab("7d", "7 days")

    def tile(lbl, val, color=""):
        return (f'<div class="card" style="flex:1;min-width:120px;text-align:center">'
                f'<div class="muted" style="font-size:.72rem;letter-spacing:.08em">{lbl}</div>'
                f'<div style="font-size:1.8rem;font-weight:800;{color}">{val}</div></div>')
    tiles = ('<div style="display:flex;gap:.6rem;flex-wrap:wrap;margin:.6rem 0">'
             + tile("TOTAL REQUESTS", total)
             + tile("UNIQUE IPS", len(ips))
             + tile("2XX SUCCESS", buckets[2], "color:var(--ok)")
             + tile("3XX REDIRECT", buckets[3])
             + tile("4XX CLIENT", buckets[4], "color:var(--warn)" if buckets[4] else "")
             + tile("5XX SERVER", buckets[5], "color:var(--err)" if buckets[5] else "")
             + '</div>')

    top_ips = sorted(ips.items(), key=lambda kv: -kv[1]["n"])[:12]
    ip_rows = "".join(
        f'<tr><td><b>{escape(ip)}</b></td><td style="text-align:right">{d["n"]}</td>'
        f'<td class="muted" style="font-size:.85rem">'
        f'{d[2]} ok · {d[3]} → · {d[4]} 4xx{(" · " + str(d[5]) + " 5xx") if d[5] else ""}</td></tr>'
        for ip, d in top_ips) or '<tr><td colspan=3 class="muted">No requests in range.</td></tr>'
    ip_card = (f'<div class="card"><h2>Top IPs by request count</h2>'
               f'<table><tr><th>IP</th><th style="text-align:right">Requests</th>'
               f'<th>Status mix</th></tr>{ip_rows}</table></div>')

    p404_rows = "".join(
        f'<tr><td>{escape(path)}</td><td style="text-align:right">{len(ipset)}</td></tr>'
        for path, ipset in sorted(p404.items(), key=lambda kv: -len(kv[1]))[:20]) \
        or '<tr><td colspan=2 class="muted">No 404s — good.</td></tr>'
    p404_card = (f'<div class="card"><h2>Top 404 paths <span class="muted">— wordlist scans '
                 f'surface here</span></h2><table><tr><th>Path</th>'
                 f'<th style="text-align:right">Distinct IPs</th></tr>{p404_rows}</table></div>')

    lg_rows = "".join(
        f'<tr><td>{escape(_ts_mt(l["ts"]))}</td><td>{escape(l["email"])}</td>'
        f'<td>{escape(l["role"])}</td>'
        f'<td>{"✓ ok" if l["result"] == "ok" else "<span style=color:var(--err)>✕ fail</span>"}</td>'
        f'<td>{escape(l["ip"])}</td></tr>'
        for l in list(reversed(logins))[:50]) or '<tr><td colspan=5 class="muted">No logins in range.</td></tr>'
    login_card = (f'<div class="card"><h2>Login events <span class="muted">— last 50</span></h2>'
                  f'<table><tr><th>When</th><th>Email</th><th>Role</th><th>Status</th><th>IP</th></tr>'
                  f'{lg_rows}</table></div>')

    # --- Audit log (compliance): durable who-did-what, from the audit_log table ---
    audit.prune()                                   # enforce retention lazily on view
    aconn = db.connect()
    arows = aconn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 50").fetchall()
    atot = aconn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    aconn.close()

    def _acolor(a, det):
        if a == "delete":
            return "color:var(--err)"
        if a == "export":
            return "color:var(--warn)"
        if a == "login":
            return "color:var(--err)" if det in ("fail", "throttled") else "color:var(--ok)"
        return ""
    audit_trs = "".join(
        f'<tr data-text="{escape(" ".join(str(x or "") for x in (r["actor_email"], r["actor_role"], r["action"], r["method"], r["path"], r["ip"], r["detail"])).lower())}">'
        f'<td style="white-space:nowrap">{escape(_ts_mt(r["ts"]))}</td>'
        f'<td>{escape(r["actor_email"] or "—")}'
        f'<br><span class="muted" style="font-size:.78rem">{escape(r["actor_role"] or "")}</span></td>'
        f'<td style="{_acolor(r["action"], r["detail"])};font-weight:700">{escape(r["action"] or "")}'
        f'{(" · " + escape(r["detail"])) if r["detail"] else ""}</td>'
        f'<td class="muted" style="font-size:.82rem">{escape((r["method"] or "") + " " + (r["path"] or ""))}</td>'
        f'<td>{r["status"] or ""}</td>'
        f'<td class="muted" style="font-size:.85rem">{escape(r["ip"] or "")}</td></tr>'
        for r in arows) or '<tr><td colspan=6 class="muted">No audit events yet.</td></tr>'
    audit_card = (
        f'<style>#atbl-wrap{{max-height:360px;overflow:auto;border:1px solid var(--line);'
        f'border-radius:8px}}#atbl thead th{{position:sticky;top:0;background:var(--panel);z-index:1}}</style>'
        f'<div class="card"><h2>Audit log <span class="muted">— who viewed / changed / '
        f'exported / deleted records · latest {len(arows)} of {atot} · kept ~13 months</span></h2>'
        f'<input id="afilter" placeholder="Filter the latest {len(arows)} by user, action, path, IP…" '
        f'oninput="afilt()" style="max-width:340px;margin-bottom:.5rem">'
        f'<div id="atbl-wrap"><table id="atbl"><thead><tr><th>When (MT)</th><th>User</th><th>Action</th>'
        f'<th>Method · Path</th><th>Status</th><th>IP</th></tr></thead><tbody>{audit_trs}</tbody></table></div>'
        f'<script>function afilt(){{var q=document.getElementById("afilter").value.toLowerCase();'
        f'document.querySelectorAll("#atbl tbody tr[data-text]").forEach(function(tr){{'
        f'tr.style.display=tr.getAttribute("data-text").indexOf(q)>-1?"":"none";}});}}</script></div>')

    stream_seed = "\n".join(_line_mt(ln) for ln in _read_journal(since, cap=200)[-200:])
    stream_card = f"""<div class="card"><h2>Raw log stream <span class="muted">— live tail</span>
<button class="ghost" onclick="PAUSED=!PAUSED;this.textContent=PAUSED?'▶ Resume':'⏸ Pause'"
  style="float:right">⏸ Pause</button></h2>
<pre id="stream" style="background:#04101f;color:#cfe;border-radius:10px;padding:.7rem;
  height:340px;overflow:auto;font-size:.74rem;line-height:1.35;white-space:pre-wrap">{escape(stream_seed)}</pre></div>
<script>
let PAUSED=false; const seen=new Set(({json.dumps(stream_seed.splitlines())}));
const el=document.getElementById('stream');
async function tail(){{ if(PAUSED)return;
  try{{ const j=await (await fetch('/admin/console/tail')).json();
    let add=''; (j.lines||[]).forEach(function(ln){{ if(!seen.has(ln)){{ seen.add(ln); add+=ln+'\\n'; }} }});
    if(add){{ const atBottom = el.scrollTop+el.clientHeight >= el.scrollHeight-30;
      el.textContent += add; if(atBottom) el.scrollTop = el.scrollHeight; }}
  }}catch(e){{}} }}
el.scrollTop = el.scrollHeight;
setInterval(tail, 3000);
</script>"""

    body = (f'<div class="row" style="justify-content:space-between;align-items:center">'
            f'<div><h1>Console <span class="pill">SUPER ADMIN</span></h1>'
            f'<p class="sub">Cross-tenant operational view — request firehose, errors, login events. '
            f'Showing the last {label}. '
            f'<a href="/admin/security">📄 Security report for district review</a></p></div>'
            f'<div>{tabs}</div></div>'
            f'{tiles}{_server_card()}{ip_card}{p404_card}{login_card}{audit_card}{stream_card}')
    return shell(g.principal, body, active="console",
                 active_district=active_district_id(), districts=_districts_for_switcher())


@bp.get("/admin/console/tail")
@role_required("super_admin")
def console_tail():
    return jsonify(lines=[_line_mt(ln) for ln in _read_journal("15 minutes ago", cap=200)[-200:]])


@bp.get("/admin/security")
@role_required("super_admin")
def security_report():
    """Detailed, print-ready security & data-protection overview for a district security
    review. Deliberately honest — states what is implemented AND what is not."""
    try:
        from .app import APP_VERSION as _v
    except Exception:  # noqa: BLE001
        _v = "current"
    today = datetime.now(_MT).strftime("%B %-d, %Y")
    css = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.65 -apple-system,Segoe UI,Roboto,system-ui,sans-serif;color:#1b2b3a;background:#eef1f5}
.doc{max-width:820px;margin:0 auto;background:#fff;padding:3rem 3.2rem 4rem;
     box-shadow:0 2px 20px rgba(20,50,80,.08)}
h1{font-size:1.7rem;color:#12385f;margin:.2rem 0 .2rem}
.meta{color:#5b6b7c;font-size:.86rem;margin-bottom:.4rem}
.conf{display:inline-block;background:#fdeeea;color:#b5451f;border:1px solid #f3c9bb;
      border-radius:6px;padding:.15rem .55rem;font-size:.72rem;font-weight:800;letter-spacing:.06em}
h2{font-size:1.12rem;color:#12385f;margin:2rem 0 .5rem;border-bottom:2px solid #e3e9f1;padding-bottom:.3rem}
h3{font-size:.98rem;margin:1rem 0 .2rem;color:#20303f}
p,li{color:#2b3d4f}
ul{margin:.35rem 0 .6rem;padding-left:1.2rem}li{margin:.18rem 0}
table{border-collapse:collapse;width:100%;margin:.6rem 0;font-size:.9rem}
th,td{border:1px solid #dbe2ea;padding:.45rem .6rem;text-align:left;vertical-align:top}
th{background:#f1f4f8;color:#33475b;font-size:.78rem;text-transform:uppercase;letter-spacing:.03em}
.ok{color:#1f7a44;font-weight:700}.part{color:#b07d16;font-weight:700}.no{color:#b5451f;font-weight:700}
.note{background:#f6f9fc;border-left:3px solid #2f6db5;padding:.6rem .9rem;margin:.7rem 0;font-size:.9rem}
.small{color:#5b6b7c;font-size:.82rem}
.toolbar{max-width:820px;margin:1.2rem auto 0;text-align:right}
.btn{background:#2f6db5;color:#fff;border:none;border-radius:8px;padding:.55rem 1.1rem;font-weight:700;cursor:pointer;font-size:.9rem}
@media print{body{background:#fff}.doc{box-shadow:none;max-width:none;padding:0}.toolbar{display:none}a{color:#12385f;text-decoration:none}}
"""
    def st(label):
        cls = {"Implemented": "ok", "Partial": "part", "Roadmap": "no",
               "Not implemented": "no"}.get(label, "")
        return f'<span class="{cls}">{label}</span>'

    body = f"""<div class="toolbar"><button class="btn" onclick="window.print()">🖨 Print / Save as PDF</button></div>
<div class="doc">
<div class="conf">CONFIDENTIAL — PREPARED FOR DISTRICT SECURITY REVIEW</div>
<h1>XCTimer — Security &amp; Data Protection Overview</h1>
<p class="meta">Generated {today} · Platform version {escape(str(_v))} · xctimer.com · Contact: admin@xctimer.com</p>
<p>XCTimer is a cross-country and track &amp; field meet-management platform for junior-high and
middle-school programs. It stores information about student athletes, so this document describes,
in detail and candidly, how that data is protected — including controls that are fully implemented
and those still on our roadmap.</p>

<h2>1. Data processed &amp; classification</h2>
<h3>Student athlete data (sensitive)</h3>
<ul>
<li>Required: name, grade, school, bib number.</li>
<li>Optional (added at a coach's discretion): date of birth, athlete/parent contact info,
emergency contacts, physical-exam dates, and signed participation waivers.</li>
<li>Competition data: meet entries, finish times, places, and team scores.</li>
</ul>
<h3>Account data</h3>
<ul><li>Staff accounts: name, email, role, and a salted one-way password hash (passwords are never
stored in plaintext or recoverable form).</li></ul>
<h3>Deliberately NOT collected</h3>
<ul><li>No Social Security numbers, no financial/payment-card data, no biometrics, and no
third-party advertising or behavioral tracking. Data is never sold or shared for marketing.</li></ul>

<h2>2. Hosting &amp; network architecture</h2>
<ul>
<li><b>Compute/storage:</b> a dedicated virtual server (Hetzner) located in the <b>United States
(Hillsboro, Oregon)</b>.</li>
<li><b>Edge:</b> Cloudflare provides TLS termination, CDN, and DDoS/WAF protection.</li>
<li><b>No public inbound:</b> the origin server is reachable <b>only</b> through a Cloudflare Tunnel —
it exposes no public inbound ports and is not directly addressable from the internet.</li>
<li><b>Data store:</b> an embedded SQLite database (WAL mode) on the server's local disk; single
application process served by a hardened WSGI server.</li>
</ul>

<h2>3. Encryption</h2>
<table><tr><th>Control</th><th>Status</th><th>Detail</th></tr>
<tr><td>In transit</td><td>{st("Implemented")}</td><td>TLS 1.2+ for all traffic, terminated at Cloudflare; HSTS enforced.</td></tr>
<tr><td>Backups at rest</td><td>{st("Implemented")}</td><td>Nightly backups are stored in an <b>encrypted</b> volume on a private, access-controlled NAS.</td></tr>
<tr><td>Live database at rest</td><td>{st("Roadmap")}</td><td>The live database sits on a private host with no public inbound access. Full-disk / database-level encryption of the live store is planned but <b>not yet enabled</b>; we disclose this rather than overstate it.</td></tr>
<tr><td>Secrets</td><td>{st("Implemented")}</td><td>API keys/credentials live in an environment file outside the web root and outside source control.</td></tr>
</table>

<h2>4. Authentication &amp; session security</h2>
<ul>
<li><b>Passwords:</b> salted one-way hashing (Werkzeug); configurable complexity minimums; one-time,
expiring email links for account setup and password reset.</li>
<li><b>Sessions:</b> 256-bit random server-side session tokens. Cookies are <b>HttpOnly</b>,
<b>Secure</b>, and <b>SameSite=Lax</b>.</li>
<li><b>Expiry:</b> idle timeout (24h) plus an absolute cap (30 days); the session ID is rotated on
login and fully invalidated on logout.</li>
<li><b>Brute-force protection:</b> server-side rate-limiting and back-off on repeated failed logins.</li>
<li><b>Multi-factor authentication:</b> {st("Implemented")} — optional per-user email-code two-step
verification. When enabled for an account, a one-time 6-digit code (10-minute expiry, limited attempts)
is emailed and required after the password; users may opt to remember a trusted device for 30 days.</li>
<li><b>Meet-day access:</b> optional no-login QR tokens let volunteer timers record finishes for a
<b>single meet only</b>. These scoped tokens grant no access to rosters, other meets, or admin functions.</li>
</ul>

<h2>5. Authorization &amp; tenant isolation</h2>
<ul>
<li><b>Roles (least privilege):</b> Super Admin, District Admin, Coach, and Timer — each limited to the
data and actions its function requires.</li>
<li><b>District isolation:</b> every record is scoped to a district; server-side authorization checks
prevent a user in one district from reading or modifying another district's data.</li>
<li><b>Model:</b> a shared database with enforced application-level tenant scoping (not per-tenant
databases); access-control checks are applied on every request server-side.</li>
</ul>

<h2>6. Application security</h2>
<ul>
<li><b>CSRF:</b> anti-forgery token (double-submit cookie) required on every state-changing request.</li>
<li><b>Content-Security-Policy:</b> restricts sources and sets <span class="small">frame-ancestors 'none'</span> (clickjacking protection).</li>
<li><b>Security headers:</b> HSTS, X-Frame-Options: DENY, X-Content-Type-Options: nosniff, Referrer-Policy, and Permissions-Policy.</li>
<li><b>Injection:</b> all database access uses parameterized queries; no string-built SQL from user input.</li>
<li><b>Output encoding:</b> user-supplied data is HTML-escaped at render time to prevent XSS.</li>
<li><b>Caching:</b> authenticated (student-data) responses are marked <span class="small">Cache-Control: no-store</span> so they are not cached by browsers or proxies.</li>
</ul>

<h2>7. Audit logging &amp; monitoring</h2>
<ul>
<li><b>Audit trail:</b> a durable log records authenticated activity — who <b>viewed, changed,
exported, or deleted</b> records — with the acting user, action, timestamp, and source IP.
Retained approximately <b>13 months</b> and reviewable by a Super Admin.</li>
<li><b>Access logging:</b> a separate per-request log (method, path, status, source IP, user) feeds a
real-time operational console (traffic, errors, login events, and host health).</li>
</ul>

<h2>8. Data retention, minimization &amp; deletion</h2>
<ul>
<li><b>Minimization:</b> only fields a meet or waiver actually needs are collected.</li>
<li><b>End-of-season deletion:</b> an administrator can permanently delete a school's athletes and all
associated personal data (contacts, DOB, parent/emergency info, waivers) at the end of a season.</li>
<li><b>Right to delete:</b> a district's or an individual student's data is removed on request.</li>
<li><b>Retention:</b> audit records are kept ~13 months (intentionally outliving deleted student data,
to evidence that deletions occurred). Backups are retained 14 days on the server and 30 days on the NAS.</li>
</ul>

<h2>9. Backups &amp; recovery</h2>
<ul>
<li>Automated nightly backups using a write-safe hot snapshot of the database (no downtime).</li>
<li>Backups include the database plus configuration needed for a cold-start restore, packaged and
stored <b>encrypted</b> on a private NAS pulled from the server over an authenticated channel.</li>
</ul>

<h2>10. Third-party sub-processors</h2>
<p>The following providers may process data in the course of delivering the service:</p>
<table><tr><th>Provider</th><th>Purpose</th><th>Data involved</th></tr>
<tr><td>Cloudflare</td><td>TLS, CDN, DDoS/WAF, secure tunnel to origin</td><td>Traffic in transit (not stored)</td></tr>
<tr><td>Hetzner</td><td>Server hosting / compute &amp; storage (US)</td><td>Data at rest on the application server</td></tr>
<tr><td>Resend</td><td>Transactional email (account setup, password reset, waiver links)</td><td>Recipient email address + message contents</td></tr>
<tr><td>Anthropic (Claude API)</td><td><b>Optional</b> AI features: roster import from an uploaded file/photo, and results-based "insights"</td><td>The relevant roster or results text is sent to the API to process the request. Per Anthropic's commercial API terms, submissions are not used to train models.</td></tr>
</table>
<div class="note">The AI features are optional conveniences. When used, the specific roster/results
content for that request transits Anthropic's API. Districts that prefer not to use them can simply
avoid the AI import and insights features; core timing and roster management do not depend on them.</div>

<h2>11. Compliance posture</h2>
<ul>
<li>Built to align with <b>FERPA</b> and <b>COPPA</b> expectations for student data: minimization,
access control, deletion on request, and audit logging.</li>
<li><b>Independent certifications:</b> {st("Not implemented")} — XCTimer does not currently hold SOC 2 and
has not undergone a third-party penetration test. We are transparent about this and can discuss a DPA
or complete a district security questionnaire on request.</li>
</ul>

<h2>12. Incident response</h2>
<ul>
<li>If a security incident affecting your data is confirmed, we will notify affected districts
<b>promptly — targeting within 72 hours</b> — with the facts known and the remediation underway.</li>
<li>Operations are US-based. A machine-readable security contact is published at
<span class="small">/.well-known/security.txt</span>.</li>
</ul>

<h2>Contact</h2>
<p>Security questions, questionnaires, DPAs, or vulnerability reports: <b>admin@xctimer.com</b>.</p>
<p class="small">This document reflects the platform as of {today} (version {escape(str(_v))}) and is provided
for a district security review. Controls evolve; contact us for the current status of any roadmap item.</p>
</div>"""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer — Security Overview</title><style>{css}</style></head><body>{body}</body></html>"""
