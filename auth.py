"""Authentication, sessions, tokens, and the meet-day QR (handoff §3, §11).

- Password login (werkzeug hashing), multi-device sessions (sessions table).
- Setup/reset via one-time expiring tokens (secrets.token_urlsafe).
- Meet-day no-login QR: /t/<token> mints a restricted meet-scoped session.
- Email via Resend API, with an SMTP fallback and a dev log fallback.
"""
import os
import functools
import secrets
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText

import requests
from markupsafe import escape
from flask import (Blueprint, request, redirect, make_response, g, abort, url_for)
from werkzeug.security import generate_password_hash, check_password_hash

from . import db
from .ui import auth_page


def _safe_next(nxt):
    """Only allow same-site relative redirects."""
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else None


def _login_body(email="", nxt=""):
    hidden = f'<input type="hidden" name="next" value="{escape(nxt)}">' if nxt else ""
    return f"""
<form method="post" action="/login">
  {hidden}
  <label>Email</label><input name="email" type="email" value="{escape(email)}" autofocus required>
  <label>Password</label><input name="password" type="password" required>
  <button type="submit">Sign in</button>
</form>
<p class="center muted"><a href="/forgot">Forgot password?</a></p>"""

bp = Blueprint("auth", __name__)

SESSION_COOKIE = "xctimer_session"
SETUP_TTL_DAYS = 7
RESET_TTL_HOURS = 1
SESSION_TTL_DAYS = 30
ROLES = ("super_admin", "district_admin", "coach", "timer")


# --- time helpers (ISO-8601, UTC) ---
def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse(s):
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _expired(s):
    dt = _parse(s)
    return dt is not None and dt < _now()


# --- principal (logged-in user OR meet-day timer) ---
class Principal:
    def __init__(self, *, user=None, session_token=None, meet_scope=None,
                 role=None, district_id=None):
        self.user = user
        self.session_token = session_token
        self.meet_scope = meet_scope        # meet_id for QR sessions, else None
        if user is not None:
            self.id = user["id"]
            self.email = user["email"]
            self.name = user["name"]
            self.role = user["role"]
            self.district_id = user["district_id"]
            self.is_demo = bool("is_demo" in user.keys() and user["is_demo"])
        else:
            self.id = None
            self.email = None
            self.name = "Meet Timer"
            self.role = role or "timer"
            self.district_id = district_id
            self.is_demo = False

    @property
    def is_super(self):
        return self.role == "super_admin"

    @property
    def is_admin(self):
        return self.role in ("super_admin", "district_admin")

    def school_ids(self):
        """Schools this principal is scoped to (coach/timer)."""
        if self.id is None:
            return set()
        conn = db.connect()
        rows = conn.execute(
            "SELECT school_id FROM user_schools WHERE user_id=?", (self.id,)
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}


# --- password + user creation ---
def hash_password(pw):
    return generate_password_hash(pw)


def verify_password(pw, pw_hash):
    return bool(pw_hash) and check_password_hash(pw_hash, pw)


def find_user_by_email(email):
    conn = db.connect()
    u = conn.execute(
        "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
    ).fetchone()
    conn.close()
    return u


def create_user(email, role, *, district_id=None, name=None, school_ids=None,
                is_demo=False, ttl_days=SETUP_TTL_DAYS):
    """Create a user with a one-time setup token. Returns (user_id, setup_token)."""
    if role not in ROLES:
        raise ValueError(f"bad role {role!r}")
    token = secrets.token_urlsafe(32)
    expires = _iso(_now() + timedelta(days=ttl_days))
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO users (district_id, email, name, role, setup_token, token_expires, is_demo) "
            "VALUES (?,?,?,?,?,?,?)",
            (district_id, email.strip().lower(), name, role, token, expires, 1 if is_demo else 0),
        )
        uid = cur.lastrowid
        for sid in (school_ids or []):
            conn.execute(
                "INSERT OR IGNORE INTO user_schools (user_id, school_id) VALUES (?,?)",
                (uid, sid),
            )
        conn.commit()
    finally:
        conn.close()
    return uid, token


def issue_reset_token(user_id):
    token = secrets.token_urlsafe(32)
    expires = _iso(_now() + timedelta(hours=RESET_TTL_HOURS))
    conn = db.connect()
    conn.execute(
        "UPDATE users SET setup_token=?, token_expires=? WHERE id=?",
        (token, expires, user_id),
    )
    conn.commit()
    conn.close()
    return token


# --- sessions ---
def create_session(user_id, *, kind="user", meet_id=None, ttl_days=SESSION_TTL_DAYS):
    token = secrets.token_urlsafe(32)
    conn = db.connect()
    conn.execute(
        "INSERT INTO sessions (token, user_id, expires, created_at, kind, meet_id) "
        "VALUES (?,?,?,?,?,?)",
        (token, user_id, _iso(_now() + timedelta(days=ttl_days)), _iso(_now()), kind, meet_id),
    )
    conn.commit()
    conn.close()
    return token


def destroy_session(token):
    if not token:
        return
    conn = db.connect()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()


def load_principal():
    """before_request hook: populate g.principal from the session cookie."""
    g.principal = None
    tok = request.cookies.get(SESSION_COOKIE)
    if not tok:
        return
    conn = db.connect()
    s = conn.execute("SELECT * FROM sessions WHERE token=?", (tok,)).fetchone()
    if not s:
        conn.close()
        return
    if _expired(s["expires"]):
        conn.execute("DELETE FROM sessions WHERE token=?", (tok,))
        conn.commit()
        conn.close()
        return
    if s["kind"] == "meet_timer":
        meet = conn.execute("SELECT * FROM meets WHERE id=?", (s["meet_id"],)).fetchone()
        conn.close()
        if not meet:
            return
        # Meet-scoped, no-login session — valid anytime, only for this one meet.
        g.principal = Principal(session_token=tok, meet_scope=s["meet_id"],
                                role="timer", district_id=meet["district_id"])
        return
    u = conn.execute("SELECT * FROM users WHERE id=?", (s["user_id"],)).fetchone()
    conn.close()
    if u:
        g.principal = Principal(user=u, session_token=tok)


# Demo accounts are read-only. These POSTs stay allowed (sign out + the
# read-only insights query the demo is meant to showcase).
_DEMO_POST_ALLOW = {"/logout", "/api/insights/ask"}


def demo_readonly_guard():
    """before_request: block mutations for demo accounts (handoff §8)."""
    p = getattr(g, "principal", None)
    if p and getattr(p, "is_demo", False) and request.method in ("POST", "PUT", "PATCH", "DELETE"):
        if request.path not in _DEMO_POST_ALLOW:
            abort(403)


def _set_session_cookie(resp, token):
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="Lax",
                    secure=bool(os.environ.get("XC_SECURE_COOKIES")),
                    max_age=SESSION_TTL_DAYS * 86400)
    return resp


# --- login throttle (audit MEDIUM-3): backoff after repeated failures ---
import time as _time  # noqa: E402

_LOGIN_FAILS = {}          # email -> [count, window_start_ts]
_MAX_FAILS = 5
_WINDOW = 900              # 15 minutes


def _login_throttled(email):
    rec = _LOGIN_FAILS.get(email)
    if not rec:
        return False
    if _time.time() - rec[1] > _WINDOW:
        _LOGIN_FAILS.pop(email, None)
        return False
    return rec[0] >= _MAX_FAILS


def _record_login_fail(email):
    now = _time.time()
    rec = _LOGIN_FAILS.get(email)
    if not rec or now - rec[1] > _WINDOW:
        _LOGIN_FAILS[email] = [1, now]
    else:
        rec[0] += 1


# --- decorators ---
def login_required(f):
    @functools.wraps(f)
    def wrapper(*a, **kw):
        if not getattr(g, "principal", None):
            return redirect("/login")
        return f(*a, **kw)
    return wrapper


def role_required(*roles):
    def deco(f):
        @functools.wraps(f)
        def wrapper(*a, **kw):
            p = getattr(g, "principal", None)
            if not p:
                return redirect("/login")
            if p.role not in roles:
                abort(403)
            return f(*a, **kw)
        return wrapper
    return deco


# --- email (Resend API -> SMTP -> dev log) ---
def send_email(to, subject, html):
    if os.environ.get("XC_MAIL_DISABLE"):
        print(f"[email:DISABLED] To {to} | {subject}\n{html}")
        return False
    key = os.environ.get("RESEND_API_KEY")
    sender = os.environ.get("XC_MAIL_FROM", "noreply@xctimer.com")
    name = os.environ.get("XC_MAIL_FROM_NAME", "XCTimer")
    frm = f"{name} <{sender}>"
    if key:
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key}"},
                json={"from": frm, "to": [to], "subject": subject, "html": html},
                timeout=15,
            )
            if r.status_code < 300:
                return True
            print(f"[email] Resend {r.status_code}: {r.text[:200]}")
        except Exception as e:  # noqa: BLE001
            print(f"[email] Resend error: {e}")
    host = os.environ.get("XC_SMTP_HOST")
    if host:
        try:
            m = MIMEText(html, "html")
            m["Subject"] = subject
            m["From"] = frm
            m["To"] = to
            with smtplib.SMTP(host, int(os.environ.get("XC_SMTP_PORT", "25"))) as srv:
                srv.send_message(m)
            return True
        except Exception as e:  # noqa: BLE001
            print(f"[email] SMTP error: {e}")
    print(f"[email:DEV] To {to} | {subject}\n{html}")
    return False


def _public_url():
    return os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))


def send_setup_email(email, token, *, reset=False):
    base = _public_url()
    link = f"{base}/setup?token={token}"
    what = "reset your password" if reset else "set up your account"
    html = (
        f"<p>Hi,</p><p>Use the link below to {what} on XCTimer:</p>"
        f'<p><a href="{link}">{link}</a></p>'
        f"<p>This link expires soon. If you didn't expect it, ignore this email.</p>"
    )
    subj = "Reset your XCTimer password" if reset else "Set up your XCTimer account"
    send_email(email, subj, html)
    return link


# ============================ routes ============================
@bp.get("/login")
def login_form():
    nxt = _safe_next(request.args.get("next")) or ""
    if getattr(g, "principal", None):
        return redirect(nxt or "/dashboard")
    return auth_page("Sign in", "Cross-country & track timing", _login_body(nxt=nxt))


@bp.post("/login")
def login_submit():
    email = (request.form.get("email") or "").strip().lower()
    pw = request.form.get("password") or ""
    nxt = _safe_next(request.form.get("next")) or ""
    if _login_throttled(email):
        return auth_page("Sign in", "Cross-country & track timing", _login_body(nxt=nxt),
                         err="Too many attempts. Please wait a few minutes and try again."), 429
    u = find_user_by_email(email)
    if not u or not verify_password(pw, u["password_hash"]):
        _record_login_fail(email)
        return auth_page("Sign in", "Cross-country & track timing", _login_body(email, nxt),
                         err="Invalid email or password."), 401
    _LOGIN_FAILS.pop(email, None)
    conn = db.connect()
    conn.execute("UPDATE users SET last_login=? WHERE id=?", (_iso(_now()), u["id"]))
    conn.commit()
    conn.close()
    token = create_session(u["id"])
    return _set_session_cookie(make_response(redirect(nxt or "/dashboard")), token)


@bp.post("/logout")
def logout():
    destroy_session(request.cookies.get(SESSION_COOKIE))
    resp = make_response(redirect("/login"))
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@bp.get("/setup")
def setup_form():
    token = request.args.get("token", "")
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE setup_token=?", (token,)).fetchone()
    conn.close()
    if not u or _expired(u["token_expires"]):
        return auth_page("Link expired", "That link is no longer valid.",
                         '<p class="center"><a href="/forgot">Request a new one</a></p>',
                         err="This setup link is invalid or has expired."), 400
    body = f"""
<form method="post" action="/setup">
  <input type="hidden" name="token" value="{token}">
  <p class="muted center">Setting password for <b>{u['email']}</b></p>
  <label>New password</label><input name="password" type="password" minlength="8" autofocus required>
  <label>Confirm password</label><input name="confirm" type="password" minlength="8" required>
  <button type="submit">Set password &amp; sign in</button>
</form>"""
    return auth_page("Set your password", "Welcome to XCTimer", body)


@bp.post("/setup")
def setup_submit():
    token = request.form.get("token", "")
    pw = request.form.get("password") or ""
    confirm = request.form.get("confirm") or ""
    conn = db.connect()
    u = conn.execute("SELECT * FROM users WHERE setup_token=?", (token,)).fetchone()
    if not u or _expired(u["token_expires"]):
        conn.close()
        return auth_page("Link expired", "That link is no longer valid.",
                         '<p class="center"><a href="/forgot">Request a new one</a></p>',
                         err="This setup link is invalid or has expired."), 400
    if len(pw) < 8 or pw != confirm:
        conn.close()
        body = f"""
<form method="post" action="/setup">
  <input type="hidden" name="token" value="{token}">
  <label>New password</label><input name="password" type="password" minlength="8" autofocus required>
  <label>Confirm password</label><input name="confirm" type="password" minlength="8" required>
  <button type="submit">Set password &amp; sign in</button>
</form>"""
        err = "Passwords must match and be at least 8 characters."
        return auth_page("Set your password", "Welcome to XCTimer", body, err=err), 400
    conn.execute(
        "UPDATE users SET password_hash=?, setup_token=NULL, token_expires=NULL, last_login=? WHERE id=?",
        (hash_password(pw), _iso(_now()), u["id"]),
    )
    conn.commit()
    conn.close()
    token = create_session(u["id"])
    return _set_session_cookie(make_response(redirect("/dashboard")), token)


@bp.get("/forgot")
def forgot_form():
    body = """
<form method="post" action="/forgot">
  <label>Email</label><input name="email" type="email" autofocus required>
  <button type="submit">Send reset link</button>
</form>
<p class="center muted"><a href="/login">Back to sign in</a></p>"""
    return auth_page("Reset password", "We'll email you a reset link", body)


@bp.post("/forgot")
def forgot_submit():
    email = (request.form.get("email") or "").strip().lower()
    u = find_user_by_email(email)
    if u:
        token = issue_reset_token(u["id"])
        send_setup_email(u["email"], token, reset=True)
    # Always report success (don't leak which emails exist).
    return auth_page("Check your email",
                     "If that address has an account, a reset link is on its way.",
                     '<p class="center"><a href="/login">Back to sign in</a></p>',
                     msg="Reset link sent if the account exists.")


# --- no-login QR: opens ONE meet's phone timing, anytime (handoff §11) ---
@bp.get("/t/<token>")
def meet_timer_link(token):
    conn = db.connect()
    meet = conn.execute("SELECT * FROM meets WHERE timer_token=?", (token,)).fetchone()
    conn.close()
    if not meet or not meet["timer_token"] or _expired(meet["timer_token_expires"]):
        return auth_page("Not available",
                         "This timer link isn't active.",
                         "<p class=center>Ask the meet host for a current link.</p>",
                         err="Link invalid or revoked."), 403
    token = create_session(None, kind="meet_timer", meet_id=meet["id"], ttl_days=1)
    # Lands on the phone timing app, scoped to this one meet.
    return _set_session_cookie(make_response(redirect("/phone")), token)
