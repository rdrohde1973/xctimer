"""Visiting teams (1.111.0): out-of-district schools at a host's meet.

A host shares ONE invite link per meet. A visiting coach opens it, enters their school and
email, and is emailed a private link (no password -- the same idea as a fun-run host's link).
That link signs them in as a guest coach, scoped to their one guest school inside the host's
district: they upload a roster and enter athletes, and nothing else.

Why a separate `guest_coaches` table instead of `users`: users.email is globally unique and a
user belongs to one district, so a coach who already has an XCTimer login anywhere (or who
visits two different hosts) could never be invited. A guest row is per (school, email).

Access is default-deny. `guest_path_ok` is the whole list of pages a guest session may open;
auth.login_required / role_required enforce it, and meets.can_record_meet / can_setup_meet
refuse guests outright, so a visiting coach can never time or run a host's meet.
"""
import io
import os
import re
import secrets
from datetime import timedelta

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, make_response, Response

from . import db
from .auth import (login_required, create_session, send_email, _public_url, _iso, _now,
                   _expired, SESSION_COOKIE)

bp = Blueprint("guest", __name__)

LINK_DAYS = 120          # how long an emailed private link stays valid
SESSION_DAYS = 60
MAX_GUESTS_PER_MEET = 80  # sanity cap on schools created through one invite link

# Everything a guest coach may open. Handlers still enforce WHICH school/meet (school_ids()).
_OK = [(m, re.compile(rx)) for m, rx in (
    ("GET", r"^/guest$"),
    ("GET", r"^/schools$"),
    ("GET", r"^/schools/\d+$"),
    ("POST", r"^/schools/\d+/(athletes|import/parse|import/commit|import/sheet|end-season)$"),
    ("GET", r"^/athletes/\d+/(card|editcard)$"),
    ("POST", r"^/athletes/\d+/(edit|info|delete|restore|sports)$"),
    ("GET", r"^/roster-template\.xlsx$"),
    ("GET", r"^/meets$"),
    ("GET", r"^/meets/\d+$"),
    ("GET", r"^/meets/\d+/assign$"),
    ("POST", r"^/meets/\d+/assign$"),
    ("GET", r"^/meets/\d+/(results|track-results)$"),
    ("GET", r"^/meets/\d+/school/\d+/(stickers|biblist)\.pdf$"),
    ("POST", r"^/(api/)?logout$"),
)]
_SCHOOL_PDF = re.compile(r"^/meets/\d+/school/(\d+)/")


def guest_path_ok(p, method, path):
    """May this guest principal make this request? (Called from the auth decorators.)"""
    if not any(m == method and rx.match(path) for m, rx in _OK):
        return False
    mm = _SCHOOL_PDF.match(path)          # a meet packet: only their own school's
    if mm and int(mm.group(1)) not in p.school_ids():
        return False
    return True


def _norm(name):
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def is_guest_school(s):
    return bool(s is not None and "guest" in s.keys() and s["guest"])


def invitable(m):
    """Meets that can take visiting teams: a district's XC or track meet, not a time trial."""
    if m["district_id"] is None or m["sport"] not in ("xc", "track"):
        return False
    return not ("time_trial" in m.keys() and m["time_trial"])


def _link_open(m):
    """The invite link works through the day after the meet."""
    d = m["date"]
    if not d:
        return True
    try:
        from datetime import date
        return date.fromisoformat(d[:10]) + timedelta(days=1) >= _now().date()
    except ValueError:
        return True


def _host_name(conn, m):
    r = conn.execute("SELECT name FROM schools WHERE id=?", (m["host_school_id"],)).fetchone() \
        if m["host_school_id"] else None
    if r:
        return r["name"]
    d = conn.execute("SELECT name FROM districts WHERE id=?", (m["district_id"],)).fetchone()
    return d["name"] if d else "the host"


def _issue_link(conn, gid):
    token = secrets.token_urlsafe(32)
    conn.execute("UPDATE guest_coaches SET token=?, token_expires=? WHERE id=?",
                 (token, _iso(_now() + timedelta(days=LINK_DAYS)), gid))
    return token


def _email_link(email, token, school, m, host):
    link = f"{_public_url()}/guest/go/{token}"
    when = f" on {escape(m['date'])}" if m["date"] else ""
    send_email(email, f"Your team link for {m['name']}",
               f"<p>{escape(host)} is hosting <b>{escape(m['name'])}</b>{when} and timing it with "
               f"XCTimer.</p><p>This is your private link for <b>{escape(school)}</b>. Use it to "
               f"upload your roster and enter your athletes:</p>"
               f'<p><a href="{link}">{link}</a></p>'
               f"<p>No password needed. Keep the link private: anyone who has it can edit your "
               f"team's roster. It works for {LINK_DAYS} days, and you can get a fresh one from "
               f"the host's invite link any time.</p>")
    return link


def _attach(conn, mid, sid):
    from .meets import assign_meet_bibs
    conn.execute("INSERT OR IGNORE INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, sid))
    assign_meet_bibs(conn, mid)


def add_guest(conn, m, school_name, email, coach_name=None, by_host=False):
    """Register a visiting team's coach for meet `m`. Returns (status, school_row_or_None).

    status: 'sent'     -- link emailed (new team, or a coach we already know)
            'home'     -- that name is one of the host district's own schools
            'taken'    -- a guest school by that name already has a roster/coach and this
                          email is not one of its coaches (never hand a roster to a stranger)
            'full'     -- too many teams came in through this link
            'invalid'  -- missing name / email
    The host (by_host=True) may add another coach to an existing guest school; the public
    form may not.
    """
    school_name = re.sub(r"\s+", " ", (school_name or "").strip())[:80]
    email = (email or "").strip().lower()
    if not school_name or "@" not in email or len(email) > 200:
        return "invalid", None
    s = next((r for r in conn.execute("SELECT * FROM schools WHERE district_id=?",
                                      (m["district_id"],)).fetchall()
              if _norm(r["name"]) == _norm(school_name)), None)
    if s is not None and not is_guest_school(s):
        return "home", s
    if s is None:
        n = conn.execute("SELECT COUNT(*) FROM meet_schools ms JOIN schools s ON s.id=ms.school_id "
                         "WHERE ms.meet_id=? AND s.guest=1", (m["id"],)).fetchone()[0]
        if n >= MAX_GUESTS_PER_MEET and not by_host:
            return "full", None
        sid = conn.execute("INSERT INTO schools (district_id, name, guest) VALUES (?,?,1)",
                           (m["district_id"], school_name)).lastrowid
        s = conn.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    gc = conn.execute("SELECT * FROM guest_coaches WHERE school_id=? AND email=?",
                      (s["id"], email)).fetchone()
    if gc is None:
        if not by_host:
            claimed = conn.execute("SELECT 1 FROM guest_coaches WHERE school_id=?", (s["id"],)).fetchone() \
                or conn.execute("SELECT 1 FROM athletes WHERE school_id=?", (s["id"],)).fetchone()
            if claimed:
                return "taken", s
        gid = conn.execute("INSERT INTO guest_coaches (school_id, email, name, created_at) VALUES (?,?,?,?)",
                           (s["id"], email, (coach_name or "").strip()[:80] or None, _iso(_now()))).lastrowid
    else:
        gid = gc["id"]
        if coach_name and not gc["name"]:
            conn.execute("UPDATE guest_coaches SET name=? WHERE id=?", (coach_name.strip()[:80], gid))
    _attach(conn, m["id"], s["id"])
    token = _issue_link(conn, gid)
    host = _host_name(conn, m)
    conn.commit()
    _email_link(email, token, s["name"], m, host)
    return "sent", s


# ------------------------------- host side -------------------------------
def ensure_invite_token(conn, mid, rotate=False):
    row = conn.execute("SELECT guest_token FROM meets WHERE id=?", (mid,)).fetchone()
    tok = row["guest_token"] if row else None
    if not tok or rotate:
        tok = secrets.token_urlsafe(12)
        conn.execute("UPDATE meets SET guest_token=? WHERE id=?", (tok, mid))
        conn.commit()
    return tok


def host_card(m):
    """'Visiting teams' card for the meet's Setup tab (shown to whoever can set the meet up)."""
    if not invitable(m):
        return ""
    mid = m["id"]
    conn = db.connect()
    tok = m["guest_token"] if "guest_token" in m.keys() else None
    rows = conn.execute(
        "SELECT s.id, s.name, "
        " (SELECT COUNT(*) FROM athletes a WHERE a.school_id=s.id AND a.active=1) AS roster "
        "FROM schools s JOIN meet_schools ms ON ms.school_id=s.id "
        "WHERE ms.meet_id=? AND s.guest=1 ORDER BY s.name", (mid,)).fetchall()
    coaches = {}
    for c in conn.execute(
            "SELECT gc.* FROM guest_coaches gc JOIN meet_schools ms ON ms.school_id=gc.school_id "
            "WHERE ms.meet_id=? ORDER BY gc.email", (mid,)).fetchall():
        coaches.setdefault(c["school_id"], []).append(c)
    conn.close()
    if tok:
        link = f"{_public_url()}/join/{tok}"
        closed = "" if _link_open(m) else (' <span style="color:var(--warn)">The meet date has passed, '
                                           'so this link is closed.</span>')
        share = (
            f'<p style="margin:.2rem 0 .5rem">Send this one link to every visiting coach. Each coach '
            f'enters their school and email, then gets a private link to upload a roster and enter '
            f'athletes. Visiting teams are free and cannot time or change your meet.{closed}</p>'
            f'<div class="row" style="gap:.5rem;align-items:center;flex-wrap:wrap">'
            f'<input id="glink" readonly value="{escape(link)}" style="flex:1;min-width:240px" '
            f'onclick="this.select()">'
            f'<button type="button" class="ghost" onclick="navigator.clipboard.writeText('
            f'document.getElementById(\'glink\').value);this.textContent=\'Copied\'">Copy</button>'
            f'<a class="btn ghost" href="/meets/{mid}/guests/qr.png" target="_blank">QR</a>'
            f'<form class="inline" method="post" action="/meets/{mid}/guests/link" '
            f'onsubmit="return confirm(\'Make a new link? The old one stops working. Coaches who '
            f'already joined keep their access.\')"><input type="hidden" name="rotate" value="1">'
            f'<button class="ghost" type="submit">New link</button></form></div>')
    else:
        share = (
            f'<p style="margin:.2rem 0 .6rem">Hosting teams from outside your district? Create one invite '
            f'link and send it to every visiting coach. They upload their own roster and enter their own '
            f'athletes. Visiting teams are free and cannot time or change your meet.</p>'
            f'<form method="post" action="/meets/{mid}/guests/link">'
            f'<button type="submit">🔗 Create invite link</button></form>')
    trs = []
    for s in rows:
        cs = coaches.get(s["id"], [])
        who = "<br>".join(
            f'{escape(c["email"])} '
            f'<span class="muted">{"signed in" if c["last_login"] else "not opened yet"}</span> '
            f'<form class="inline" method="post" action="/meets/{mid}/guests/{c["id"]}/resend">'
            f'<button class="ghost" type="submit" style="padding:.1rem .45rem;font-size:.78rem">Resend</button></form>'
            f'<form class="inline" method="post" action="/meets/{mid}/guests/{c["id"]}/remove" '
            f'onsubmit="return confirm(\'Remove this coach\\\'s access? The roster stays.\')">'
            f'<button class="ghost" type="submit" style="padding:.1rem .45rem;font-size:.78rem">Remove</button></form>'
            for c in cs) or '<span class="muted">no coach yet</span>'
        roster = (f'{s["roster"]} athletes' if s["roster"]
                  else '<span style="color:var(--warn)">no roster yet</span>')
        trs.append(f'<tr><td><b>{escape(s["name"])}</b></td><td>{roster}</td><td>{who}</td></tr>')
    table = (f'<table style="margin-top:.8rem"><tr><th>Visiting team</th><th>Roster</th><th>Coach</th></tr>'
             f'{"".join(trs)}</table>' if trs else "")
    add = (
        f'<details style="margin-top:.8rem"><summary>Add a visiting team or coach yourself</summary>'
        f'<form method="post" action="/meets/{mid}/guests/add" class="row" '
        f'style="gap:.5rem;align-items:flex-end;flex-wrap:wrap;margin-top:.5rem">'
        f'<div><label>School</label><input name="school" required placeholder="Lincoln High"></div>'
        f'<div><label>Coach email</label><input name="email" type="email" required></div>'
        f'<div><button type="submit">Email their link</button></div></form>'
        f'<p class="muted" style="font-size:.85rem;margin:.4rem 0 0">Use the same school name to add a '
        f'second coach to a team already listed.</p></details>')
    return f'<div class="card" id="visiting"><h2>Visiting teams</h2>{share}{table}{add}</div>'


def _host_meet(mid):
    from .meets import load_meet, can_setup_meet
    m = load_meet(mid)
    if not can_setup_meet(m) or not invitable(m):
        abort(403)
    return m


@bp.post("/meets/<int:mid>/guests/link")
@login_required
def make_link(mid):
    _host_meet(mid)
    conn = db.connect()
    ensure_invite_token(conn, mid, rotate=bool(request.form.get("rotate")))
    conn.close()
    return redirect(f"/meets/{mid}#visiting")


@bp.get("/meets/<int:mid>/guests/qr.png")
@login_required
def invite_qr(mid):
    import qrcode
    m = _host_meet(mid)
    if not m["guest_token"]:
        abort(404)
    buf = io.BytesIO()
    qrcode.make(f"{_public_url()}/join/{m['guest_token']}").save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


@bp.post("/meets/<int:mid>/guests/add")
@login_required
def host_add(mid):
    m = _host_meet(mid)
    conn = db.connect()
    status, _s = add_guest(conn, m, request.form.get("school"), request.form.get("email"), by_host=True)
    conn.close()
    note = {"sent": "msg=Link+emailed+to+the+visiting+coach",
            "home": "err=That+school+is+one+of+your+own+schools.+Tick+it+under+Schools+at+this+meet.",
            "invalid": "err=Enter+a+school+name+and+a+valid+email"}.get(status, "err=Could+not+add+that+team")
    return redirect(f"/meets/{mid}?{note}#visiting")


def _coach_at_meet(conn, mid, gid):
    return conn.execute(
        "SELECT gc.*, s.name AS sname FROM guest_coaches gc JOIN schools s ON s.id=gc.school_id "
        "JOIN meet_schools ms ON ms.school_id=gc.school_id WHERE gc.id=? AND ms.meet_id=? AND s.guest=1",
        (gid, mid)).fetchone()


@bp.post("/meets/<int:mid>/guests/<int:gid>/resend")
@login_required
def host_resend(mid, gid):
    m = _host_meet(mid)
    conn = db.connect()
    c = _coach_at_meet(conn, mid, gid)
    if not c:
        conn.close()
        abort(404)
    token = _issue_link(conn, gid)
    host = _host_name(conn, m)
    conn.commit()
    conn.close()
    _email_link(c["email"], token, c["sname"], m, host)
    return redirect(f"/meets/{mid}?msg=Link+re-sent#visiting")


@bp.post("/meets/<int:mid>/guests/<int:gid>/remove")
@login_required
def host_remove(mid, gid):
    _host_meet(mid)
    conn = db.connect()
    if not _coach_at_meet(conn, mid, gid):
        conn.close()
        abort(404)
    conn.execute("DELETE FROM sessions WHERE guest_id=?", (gid,))
    conn.execute("DELETE FROM guest_coaches WHERE id=?", (gid,))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}?msg=Coach+access+removed#visiting")


# ------------------------------- visiting coach: join -------------------------------
def _page(title, inner):
    from .road import _host_page
    return _host_page(title, inner)


def _meet_by_invite(token):
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE guest_token=?", (token,)).fetchone() if token else None
    host = _host_name(conn, m) if m else None
    conn.close()
    if not m or not invitable(m):
        abort(404)
    return m, host


@bp.get("/join/<token>")
def join_form(token):
    m, host = _meet_by_invite(token)
    when = f" · {escape(m['date'])}" if m["date"] else ""
    sport = "Track & Field" if m["sport"] == "track" else "Cross Country"
    head = (f'<h1>{escape(m["name"])}</h1><p style="margin-top:-.4rem">{sport}{when}<br>'
            f'Hosted by <b>{escape(host)}</b></p>')
    if not _link_open(m):
        return _page(m["name"], f'<div class="card">{head}<p>Sign-up for this meet has closed. '
                                f'Contact the host if you still need to enter a team.</p></div>')
    return _page(m["name"], f"""<div class="card">{head}
<p>Bringing a team? Enter your school and email. We will email you a private link to upload your
roster and enter your athletes. It is free for visiting teams, and there is no password to set.</p>
<form method="post" action="/join/{escape(token)}">
  <label>School</label><input name="school" required maxlength="80" placeholder="Lincoln High School">
  <label>Your name</label><input name="name" maxlength="80" placeholder="Coach Rivera">
  <label>Your email</label><input name="email" type="email" required maxlength="200">
  <p style="margin:1rem 0 0"><button class="btn" type="submit">Email my team link →</button></p>
</form>
<p style="font-size:.9rem;color:#5b6b7b">Already signed up? Enter the same school and email to get a fresh link.</p>
</div>""")


@bp.post("/join/<token>")
def join_submit(token):
    m, host = _meet_by_invite(token)
    if not _link_open(m):
        abort(404)
    school = (request.form.get("school") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    conn = db.connect()
    status, s = add_guest(conn, m, school, email, request.form.get("name"))
    conn.close()
    back = f'<a href="/join/{escape(token)}">← Back</a>'
    if status == "sent":
        return _page("Check your email",
                     f'<div class="card"><h1>✅ Check your email</h1><p>We emailed <b>{escape(email)}</b> a '
                     f'private link for <b>{escape(s["name"])}</b> at {escape(m["name"])}. Open it to upload '
                     f'your roster.</p><p>It comes from <b>XCTimer</b>. Check your spam folder if it does not '
                     f'arrive in a few minutes. Wrong address? {back}</p></div>')
    if status == "home":
        return _page("Already part of this meet",
                     f'<div class="card"><h1>{escape(s["name"])} is a host-district school</h1><p>Its coaches '
                     f'sign in with their regular XCTimer account. <a href="/login">Sign in</a> or {back}</p></div>'), 400
    if status == "taken":
        return _page("Team already registered",
                     f'<div class="card"><h1>{escape(s["name"])} is already registered</h1><p>Another coach '
                     f'set this team up. For the privacy of the roster, we can only send the link to an email '
                     f'already on the team. Ask that coach, or ask {escape(host)} to add you. {back}</p></div>'), 400
    if status == "full":
        return _page("Sign-up is full",
                     f'<div class="card"><h1>Sign-up is full</h1><p>Contact {escape(host)} to enter your team. '
                     f'{back}</p></div>'), 400
    return _page("Check your entry", f'<div class="card">Please enter your school and a valid email. {back}</div>'), 400


@bp.get("/guest/go/<token>")
def guest_go(token):
    conn = db.connect()
    c = conn.execute("SELECT * FROM guest_coaches WHERE token=?", (token,)).fetchone() if token else None
    if not c or _expired(c["token_expires"]):
        conn.close()
        return _page("Link expired",
                     '<div class="card"><h1>That link has expired</h1><p>Open the invite link the meet host '
                     'sent you and enter your school and email again. We will send a fresh one.</p></div>'), 404
    conn.execute("UPDATE guest_coaches SET last_login=? WHERE id=?", (_iso(_now()), c["id"]))
    conn.commit()
    conn.close()
    tok = create_session(None, kind="guest_coach", guest_id=c["id"], ttl_days=SESSION_DAYS)
    resp = make_response(redirect("/guest"))
    resp.set_cookie(SESSION_COOKIE, tok, httponly=True, samesite="Lax",
                    secure=bool(os.environ.get("XC_SECURE_COOKIES")), max_age=SESSION_DAYS * 86400)
    return resp


# ------------------------------- visiting coach: home -------------------------------
@bp.get("/guest")
@login_required
def guest_home():
    from .ui import shell
    p = g.principal
    if not getattr(p, "guest", False):
        return redirect("/")
    sid = next(iter(p.school_ids()))
    conn = db.connect()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    n = conn.execute("SELECT COUNT(*) FROM athletes WHERE school_id=? AND active=1", (sid,)).fetchone()[0]
    meets = conn.execute(
        "SELECT m.* FROM meets m JOIN meet_schools ms ON ms.meet_id=m.id WHERE ms.school_id=? "
        "ORDER BY (m.date IS NULL), m.date DESC, m.id DESC", (sid,)).fetchall()
    cards = []
    for m in meets:
        host = _host_name(conn, m)
        entered = conn.execute(
            "SELECT COUNT(*) FROM meet_bibs mb JOIN athletes a ON a.id=mb.athlete_id "
            "WHERE mb.meet_id=? AND a.school_id=?", (m["id"], sid)).fetchone()[0]
        results = (f' <a class="btn ghost" href="/r/{m["public_token"]}">Live results</a>'
                   if m["public_token"] else "")
        if m["sport"] == "track":
            in_events = conn.execute(
                "SELECT COUNT(DISTINCT en.runner_id) FROM entries en JOIN meet_events me ON me.id=en.meet_event_id "
                "JOIN athletes a ON a.id=en.runner_id WHERE me.meet_id=? AND a.school_id=?",
                (m["id"], sid)).fetchone()[0]
            status = (f'<b>{in_events}</b> of {entered} track athletes are entered in events.'
                      if entered else 'Mark athletes for <b>Track</b> on your roster, then enter them in events.')
            act = f'<a class="btn" href="/meets/{m["id"]}/assign?school={sid}">Enter athletes in events</a>'
        else:
            status = (f'<b>{entered}</b> runners entered. Everyone on your roster marked for '
                      f'<b>Cross Country</b> is entered automatically.' if entered else
                      'No runners entered yet. Upload your roster and mark runners for <b>Cross Country</b>.')
            act = f'<a class="btn ghost" href="/meets/{m["id"]}">Meet details</a>'
        when = f' · {escape(m["date"])}' if m["date"] else ""
        cards.append(
            f'<div class="card"><h2 style="margin-bottom:.2rem">{escape(m["name"])}</h2>'
            f'<p class="muted" style="margin:0 0 .6rem">{"Track & Field" if m["sport"] == "track" else "Cross Country"}'
            f'{when} · hosted by {escape(host)}</p><p>{status}</p>{act}{results}</div>')
    conn.close()
    roster = (f'<b>{n}</b> athletes on your roster.' if n else
              'Your roster is empty. Upload a spreadsheet, PDF or photo, or paste a Google Sheet link.')
    body = (f'<h1>{escape(s["name"])}</h1><p class="sub">Visiting team. You can manage your roster and '
            f'your entries here. Timing and meet setup belong to the host.</p>'
            f'<div class="card"><h2>1. Your roster</h2><p>{roster}</p>'
            f'<a class="btn" href="/schools/{sid}">{"Open roster" if n else "Upload roster"}</a></div>'
            f'<h2 style="margin:1.2rem 0 .6rem">2. Your meets</h2>'
            + ("".join(cards) or '<div class="card muted">No meets yet.</div>'))
    return shell(p, body, active="guest", msg=request.args.get("msg"))
