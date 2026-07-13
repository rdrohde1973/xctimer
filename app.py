"""XCTimer platform — Flask app factory & boot (handoff §5).

Phase 0 scaffold: app factory, blueprint registration, DB init on boot, a neutral
landing page + health check. Real auth/tenancy/engines land in later phases.

Run (dev):   python -m xctimer.app         (or waitress via the systemd unit)
Serve:       waitress on XC_HOST:XC_PORT    (defaults 127.0.0.1:5006)
"""
import os

from flask import Flask, jsonify, render_template_string

from . import db
from .auth import bp as auth_bp
from .tenancy import bp as tenancy_bp
from .schools import bp as schools_bp
from .meets import bp as meets_bp
from .xc import bp as xc_bp
from .track import bp as track_bp

APP_VERSION = "0.0.1-scaffold"

LANDING = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer</title>
<style>
  :root { color-scheme: light dark; }
  body { margin:0; font:16px/1.5 system-ui,sans-serif; display:grid; place-items:center;
         min-height:100vh; background:#0b1220; color:#e7edf5; }
  .card { text-align:center; padding:2.5rem 3rem; }
  h1 { font-size:2.4rem; margin:.2em 0; letter-spacing:-.02em; }
  .tag { color:#8aa0b6; }
  .v { margin-top:1.5rem; font-size:.8rem; color:#5f7488; }
</style></head><body>
  <div class=card>
    <h1>🏃 XCTimer</h1>
    <p class=tag>Cross-country &amp; track timing — multi-district platform</p>
    <p class=v>{{ version }} · scaffold up · phase 0</p>
  </div>
</body></html>"""


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("XCTIMER_SECRET", "dev-insecure-change-me")

    db.init_db()

    app.register_blueprint(auth_bp)
    app.register_blueprint(tenancy_bp)
    app.register_blueprint(schools_bp)
    app.register_blueprint(meets_bp)
    app.register_blueprint(xc_bp)
    app.register_blueprint(track_bp)

    @app.get("/")
    def landing():
        return render_template_string(LANDING, version=APP_VERSION)

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
