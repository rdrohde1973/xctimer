"""XCTimer platform — Flask app factory & boot (handoff §5).

Phase 1: password auth + email setup/reset links, multi-device sessions, the 4
roles, district scoping + Super-Admin switcher, user/district/school management,
and the meet-day no-login QR session. XC/Track engines land in Phases 3-4.

Serve: waitress on XC_HOST:XC_PORT (defaults 127.0.0.1:5006), via the systemd unit.
"""
import os

from flask import Flask, jsonify, g, redirect

from . import db, auth
from .auth import bp as auth_bp
from .tenancy import bp as tenancy_bp
from .schools import bp as schools_bp
from .meets import bp as meets_bp
from .xc import bp as xc_bp
from .track import bp as track_bp
from .admin import bp as admin_bp
from .insights import bp as insights_bp
from .phone import bp as phone_bp
from .waivers import bp as waivers_bp

APP_VERSION = "0.19.1-bibqr"

LANDING = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer — cross-country &amp; track timing</title>
<style>
  :root{--navy:#164271;--orange:#ea6a2d;--orange-d:#cf5a22;--gray:#868686}
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;flex-direction:column;
       align-items:center;justify-content:center;padding:2rem 1.2rem;
       font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--navy);
       background:radial-gradient(120% 120% at 50% 0%,#ffffff 0%,#eef1f5 60%,#e5e9ef 100%)}
  .hero{text-align:center;max-width:640px}
  .hero img{width:min(560px,88vw);height:auto;filter:drop-shadow(0 8px 30px rgba(22,66,113,.15))}
  .tag{margin:1.2rem 0 2rem;font-size:1.15rem;color:var(--navy);opacity:.85}
  .tag b{color:var(--orange)}
  a.btn{display:inline-block;background:var(--orange);color:#fff;font-weight:700;
        padding:.7rem 1.8rem;border-radius:11px;text-decoration:none;font-size:1.05rem;
        box-shadow:0 6px 18px rgba(234,106,45,.35)}
  a.btn:hover{background:var(--orange-d)}
  .feats{margin-top:2.6rem;display:flex;gap:1.4rem;flex-wrap:wrap;justify-content:center;
         color:var(--gray);font-size:.92rem}
  .feats span{white-space:nowrap}
  footer{margin-top:auto;padding-top:2.4rem;color:var(--gray);font-size:.8rem}
</style></head><body>
  <div class="hero">
    <img src="/static/branding/xctimer.png" alt="XCTimer">
    <p class="tag">One platform for <b>cross-country</b> &amp; <b>track &amp; field</b> — across every district.</p>
    <a class="btn" href="/login">Sign in</a>
    <div class="feats">
      <span>⏱️ Live timing console</span><span>📋 Rosters &amp; bib stickers</span>
      <span>🏆 Team scoring</span><span>📱 Meet-day QR</span>
    </div>
  </div>
  <footer>xctimer.com</footer>
</body></html>"""


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("XCTIMER_SECRET", "dev-insecure-change-me")
    # Cookie hardening (security audit MEDIUM-2). SECURE only in prod (behind
    # HTTPS at Cloudflare) — XC_SECURE_COOKIES=1 there; unset on LAN http dev.
    _secure = bool(os.environ.get("XC_SECURE_COOKIES"))
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_secure,
    )

    db.init_db()

    app.before_request(auth.load_principal)
    app.before_request(auth.demo_readonly_guard)

    for bp in (auth_bp, tenancy_bp, schools_bp, meets_bp, xc_bp, track_bp,
               admin_bp, insights_bp, phone_bp, waivers_bp):
        app.register_blueprint(bp)

    @app.get("/")
    def landing():
        if getattr(g, "principal", None):
            from .ui import home_url
            return redirect(home_url(g.principal))
        return LANDING

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=APP_VERSION)

    @app.get("/manifest.webmanifest")
    def manifest():
        # PWA manifest so "Add to Home Screen" installs a clean standalone app.
        return jsonify({
            "name": "XCTimer", "short_name": "XCTimer",
            "start_url": "/phone", "scope": "/",
            "display": "standalone", "orientation": "portrait",
            "background_color": "#0a1728", "theme_color": "#0a1728",
            "icons": [
                {"src": "/static/branding/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/branding/icon-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "any maskable"},
            ],
        })

    @app.get("/.well-known/security.txt")
    def security_txt():
        from datetime import datetime, timedelta, timezone
        from flask import Response
        exp = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = os.environ.get("XC_PUBLIC_URL", "https://xctimer.com")
        body = (f"Contact: mailto:rob@shasta.cloud\n"
                f"Expires: {exp}\n"
                f"Preferred-Languages: en\n"
                f"Canonical: {base}/.well-known/security.txt\n")
        return Response(body, mimetype="text/plain")

    @app.after_request
    def _security_headers(resp):
        # HTTP security headers (audit HIGH-1). Belt-and-suspenders with Cloudflare.
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # Inline <style>/<script> are used throughout, so 'unsafe-inline' is required;
        # frame-ancestors 'none' is the key clickjacking win.
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if _secure:
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        # Don't let authenticated pages sit in caches (audit LOW-1).
        if getattr(g, "principal", None):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Pragma"] = "no-cache"
        return resp

    from .ui import error_page

    @app.errorhandler(403)
    def _e403(e):
        return error_page(403, "Not allowed", "You don't have access to that."), 403

    @app.errorhandler(404)
    def _e404(e):
        return error_page(404, "Not found", "That page or record doesn't exist."), 404

    @app.errorhandler(500)
    def _e500(e):
        return error_page(500, "Something went wrong", "An unexpected error occurred."), 500

    return app


app = create_app()


def main():
    from waitress import serve

    host = os.environ.get("XC_HOST", "127.0.0.1")
    port = int(os.environ.get("XC_PORT", "5006"))
    print(f"XCTimer {APP_VERSION} serving on {host}:{port}")
    serve(app, host=host, port=port)


if __name__ == "__main__":
    main()
