"""Dashboard + district and user management (handoff §2, §4) — Phase 1.

Districts: super admin only. Users: super admin (any district) and district admin
(own district). Every write is district-scoped server-side.
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_MT = ZoneInfo("America/Denver")   # Mountain Time (handles MST/MDT)

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, jsonify, Response

from . import db
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

    # Coaches/timers have no use for the admin dashboard — send them to Meets.
    if p.role in ("coach", "timer") and not p.meet_scope:
        return redirect("/meets")

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
            f'<td style="text-align:right">'
            f'<form class="inline" method="post" action="/districts/{d["id"]}/delete" '
            f'onsubmit="return confirm(\'Delete {escape(d["name"])} and ALL its data?\')">'
            f'<button class="danger" type="submit">Delete</button></form></td></tr>'
        )
    table = (f'<div class="card"><table><tr><th>District</th><th>Logo</th><th>Schools</th>'
             f'<th>Users</th><th>Public results</th><th></th></tr>{"".join(body_rows)}</table></div>'
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
    if not conn.execute("SELECT 1 FROM districts WHERE id=?", (did,)).fetchone():
        conn.close()
        abort(404)
    # Cascade the (still-small in Phase 1) child rows.
    conn.execute("DELETE FROM user_schools WHERE school_id IN "
                 "(SELECT id FROM schools WHERE district_id=?)", (did,))
    conn.execute("DELETE FROM schools WHERE district_id=?", (did,))
    conn.execute("DELETE FROM users WHERE district_id=?", (did,))
    conn.execute("DELETE FROM meets WHERE district_id=?", (did,))
    conn.execute("DELETE FROM districts WHERE id=?", (did,))
    conn.commit()
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
           + "<th>Status</th><th>Last login</th><th></th></tr>")

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
        trs.append(
            f'<tr><td><b>{escape(u["name"] or "")}</b><br>'
            f'<span class="muted">{escape(u["email"])}</span></td>'
            f'<td>{role_cell}</td>'
            f'{dcol}<td>{status}</td>'
            f'<td>{_fmt_login(u["last_login"])}</td>'
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
            f'Showing the last {label}.</p></div><div>{tabs}</div></div>'
            f'{tiles}{ip_card}{p404_card}{login_card}{stream_card}')
    return shell(g.principal, body, active="console",
                 active_district=active_district_id(), districts=_districts_for_switcher())


@bp.get("/admin/console/tail")
@role_required("super_admin")
def console_tail():
    return jsonify(lines=[_line_mt(ln) for ln in _read_journal("15 minutes ago", cap=200)[-200:]])
