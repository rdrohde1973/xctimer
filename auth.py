"""Authentication & sessions (handoff §3) — Phase 1.

To build here:
  - Password login (werkzeug.security generate/check_password_hash).
  - Setup/reset flows via one-time expiring tokens (secrets.token_urlsafe(32)):
      * user creation by admin -> emailed setup link /setup?token=...
      * first-time set-password -> token consumed -> auto sign-in
      * forgot-password reset (same token mechanism, 1h expiry)
  - Multi-device sessions (sessions table: token, user_id, expires, created_at);
    cookie name 'xctimer_session'.
  - current_user() helper + @login_required / role decorators.
  - Meet-day no-login QR (handoff §11): /t/<token> -> validate meet.timer_token,
    check meet.date == today server-side, mint a restricted ephemeral session
    scoped to a single meet_id (Timer-role recording UI only), auto-expiring EOD.
  - Email via Resend API (RESEND_API_KEY), SMTP fallback; port _send_invite_email.
"""
from flask import Blueprint

bp = Blueprint("auth", __name__)

SESSION_COOKIE = "xctimer_session"

# Placeholder so the blueprint is non-empty; real routes land in Phase 1.
@bp.get("/login")
def login():
    return "login — not yet implemented (Phase 1)", 501
