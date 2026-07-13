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

APP_VERSION = "0.2.0-phase2"

LANDING = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font:16px/1.5 system-ui,sans-serif; display:grid; place-items:center;
         min-height:100vh; background:#0b1220; color:#e7edf5; }
  .card { text-align:center; padding:2.5rem 3rem; }
  h1 { font-size:2.6rem; margin:.2em 0; letter-spacing:-.02em; }
  .tag { color:#8aa0b6; margin-bottom:1.6rem; }
  a.btn { display:inline-block; background:#4f9cf9; color:#04101f; font-weight:700;
          padding:.6rem 1.4rem; border-radius:10px; text-decoration:none; }
  a.btn:hover { background:#2f7de0; }
</style></head><body>
  <div class=card>
    <h1>🏃 XCTimer</h1>
    <p class=tag>Cross-country &amp; track timing — multi-district platform</p>
    <a class=btn href="/login">Sign in</a>
  </div>
</body></html>"""


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("XCTIMER_SECRET", "dev-insecure-change-me")

    db.init_db()

    app.before_request(auth.load_principal)

    for bp in (auth_bp, tenancy_bp, schools_bp, meets_bp, xc_bp, track_bp, admin_bp):
        app.register_blueprint(bp)

    @app.get("/")
    def landing():
        if getattr(g, "principal", None):
            return redirect("/dashboard")
        return LANDING

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=APP_VERSION)

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
