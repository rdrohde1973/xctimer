"""Course maps: plot a meet's course on satellite imagery; spectators get a fly-over.

The host drops points along the course on a satellite map (/meets/<id>/course). Only
those clicked points are stored -- smoothing, distance, loop colouring and mile marks
are all worked out in the browser by static/course.js, the same code on both pages, so
the editor and the results-page viewer can never disagree about a course.

Spectators open /r/<token>/course from the public results page: a 30-second fly-over
along the route over 3D terrain, mile marks lighting up as it passes, each repeat loop
in its own colour, then a zoom out to the whole course and confetti.

Imagery: Esri World Imagery with a free ArcGIS developer key (XC_ESRI_KEY in env; no
card on file means going over the free tier BLOCKS tiles, never bills). Without a key
it falls back to public-domain USGS imagery, which stops sharpening at zoom 16.
Elevation: AWS Terrain Tiles (open data). Place search: OpenStreetMap Nominatim.

These pages load third-party map data, which the site-wide CSP forbids, so each sets
its own policy naming exactly those hosts. Every other page keeps the strict one.
"""
import json
import math
import os

from flask import Blueprint, request, abort, jsonify, g, make_response, redirect
from markupsafe import escape

from . import db
from .auth import login_required
from .meets import load_meet, can_setup_meet, can_view_meet
from .ui import shell

bp = Blueprint("coursemap", __name__)

MAX_COURSES, MAX_POINTS, MAX_NAME = 6, 3000, 60
_WORKER = "/static/vendor/maplibre/maplibre-gl-csp-worker.js"
_DEM = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

_MAP_HOSTS = ("https://ibasemaps-api.arcgis.com https://basemap.nationalmap.gov "
              "https://s3.amazonaws.com")
_MAP_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: blob: {_MAP_HOSTS}; "
            f"connect-src 'self' {_MAP_HOSTS} https://nominatim.openstreetmap.org; "
            "worker-src 'self' blob:; child-src 'self' blob:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


def _tiles():
    key = (os.environ.get("XC_ESRI_KEY") or "").strip()
    if key:
        return {"url": ("https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/"
                        "MapServer/tile/{z}/{y}/{x}?token=" + key),
                "maxzoom": 19, "sharp": True,
                "attribution": "Powered by Esri · Esri, Maxar, Earthstar Geographics"}
    return {"url": ("https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/"
                    "MapServer/tile/{z}/{y}/{x}"),
            "maxzoom": 16, "sharp": False,
            "attribution": "USGS The National Map: Orthoimagery"}


def _config(**kw):
    """JSON for a <script type=application/json> block. Every <, > and & is written as a
    \\u escape (still valid JSON, parsed back to the same text), so nothing a host types
    into a course name can close the block, open a comment or start a tag -- the same
    approach as Django's json_script."""
    cfg = {"tiles": _tiles(), "dem": _DEM, "worker": _WORKER,
           "demAttribution": "Elevation: Mapzen / AWS Terrain Tiles"}
    cfg.update(kw)
    return (json.dumps(cfg).replace("&", "\\u0026").replace("<", "\\u003c")
            .replace(">", "\\u003e"))


def _map_page(html, geolocation=False):
    resp = make_response(html)
    resp.headers["Content-Security-Policy"] = _MAP_CSP
    if geolocation:     # "Use my location" in the editor
        resp.headers["Permissions-Policy"] = "geolocation=(self), microphone=(), camera=()"
    return resp


def load_course(m):
    try:
        data = json.loads(m["course_json"] or "null") if "course_json" in m.keys() else None
    except ValueError:
        data = None
    return data if isinstance(data, dict) else None


def has_course(m):
    """True when at least one course has a route to show."""
    d = load_course(m)
    return bool(d) and any(len(c.get("points") or []) >= 2 for c in d.get("courses", []))


def clean(data):
    """Validate a posted course document. Raises ValueError with a readable reason."""
    if not isinstance(data, dict):
        raise ValueError("bad payload")
    courses = data.get("courses")
    if not isinstance(courses, list) or not 1 <= len(courses) <= MAX_COURSES:
        raise ValueError(f"between 1 and {MAX_COURSES} courses")
    out = []
    for c in courses:
        if not isinstance(c, dict):
            raise ValueError("bad course")
        name = str(c.get("name") or "").strip()[:MAX_NAME] or "Course"
        pts = c.get("points") or []
        if not isinstance(pts, list) or len(pts) > MAX_POINTS:
            raise ValueError(f"at most {MAX_POINTS} points per course")
        good = []
        for p in pts:
            try:
                lng, lat = float(p[0]), float(p[1])
            except (TypeError, ValueError, IndexError):
                raise ValueError("bad point")
            if not (math.isfinite(lng) and math.isfinite(lat) and -180 <= lng <= 180 and -90 <= lat <= 90):
                raise ValueError("point off the map")
            good.append([round(lng, 7), round(lat, 7)])
        out.append({"name": name, "points": good, "smooth": bool(c.get("smooth", True))})
    view = None
    v = data.get("view")
    if isinstance(v, dict):
        try:
            lng, lat, z = float(v["center"][0]), float(v["center"][1]), float(v["zoom"])
            if all(math.isfinite(x) for x in (lng, lat, z)) and -180 <= lng <= 180 \
                    and -90 <= lat <= 90 and 0 <= z <= 22:
                view = {"center": [round(lng, 7), round(lat, 7)], "zoom": round(z, 2)}
        except (KeyError, TypeError, ValueError, IndexError):
            view = None
    return {"version": 1, "courses": out, "view": view}


def _tabs(m):
    from .xc import _xc_tabs, _is_org
    return _xc_tabs(m["id"], "course", road=(m["sport"] == "road"), organizer=_is_org(m))


# ------------------------------------------------------------------ editor
@bp.get("/meets/<int:mid>/course")
@login_required
def course_editor(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    if m["sport"] not in ("xc", "road"):
        abort(404)
    if not can_setup_meet(m):
        # Coaches and viewers get the spectator map, not the editor.
        if has_course(m):
            return redirect(f"/r/{m['public_token']}/course")
        body = (f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
                f'<h1>{escape(m["name"])}</h1>{_tabs(m)}'
                '<div class="card muted">No course map yet — the host adds it here.</div>')
        return shell(g.principal, body, active="meets")
    cfg = _config(save=f"/meets/{mid}/course", data=load_course(m),
                  preview=f"/r/{m['public_token']}/course", meetName=m["name"])
    sharp = "" if _tiles()["sharp"] else (
        '<div class="msg warn" style="margin:.4rem 0">Using public-domain USGS imagery, which '
        'goes blurry when you zoom in close. Adding a free Esri key makes it sharp.</div>')
    body = f"""
<link rel="stylesheet" href="/static/vendor/maplibre/maplibre-gl.css">
<link rel="stylesheet" href="/static/course.css">
<p class="muted"><a href="/meets/{mid}">← {escape(m['name'])}</a></p>
<h1>🗺 Course map <span class="muted" style="font-weight:400">· {escape(m['name'])}</span></h1>
{_tabs(m)}
{sharp}
<div class="card cm-bar">
  <form id="cm-search" class="cm-row">
    <input id="cm-q" placeholder="Find the course — park, school or address" autocomplete="off">
    <button type="submit">Find</button>
    <button type="button" class="ghost" id="cm-here">📍 My location</button>
  </form>
  <div class="cm-row">
    <select id="cm-course" aria-label="Course"></select>
    <button type="button" class="ghost" id="cm-add">+ Add course</button>
    <button type="button" class="ghost" id="cm-rename">Rename</button>
    <button type="button" class="ghost" id="cm-del">Delete course</button>
  </div>
</div>
<div id="cm-map" class="cm-map"></div>
<div class="card cm-bar">
  <div class="cm-stats" id="cm-stats"></div>
  <div class="cm-row">
    <button type="button" class="ghost" id="cm-undo">↶ Undo</button>
    <button type="button" class="ghost" id="cm-delpt" disabled>✕ Delete point</button>
    <button type="button" class="ghost" id="cm-repeat" disabled title="Tap the point where a loop starts, then repeat it">🔁 Repeat loop</button>
    <button type="button" class="ghost" id="cm-clear">Clear</button>
    <label class="cm-check"><input type="checkbox" id="cm-smooth"> Smooth the route</label>
    <span style="flex:1"></span>
    <a class="btn ghost" id="cm-preview" target="_blank" rel="noopener" href="/r/{escape(m['public_token'])}/course">▶ Preview fly-over</a>
    <button type="button" id="cm-save">💾 Save</button>
  </div>
  <p class="muted cm-help">Click the map to drop points along the course, from the start line to the
  finish. Drag a point to move it; tap one and press <b>Delete point</b> to remove it. When the route
  goes back over ground it already covered, that loop turns a new colour automatically. <b>Same loop
  twice?</b> Draw it once, tap the point where the loop starts, and press <b>Repeat loop</b>. Tick
  <b>Smooth the route</b> once it's all in to round off the corners — it still passes through every point.</p>
</div>
<script type="application/json" id="cm-config">{cfg}</script>
<script src="/static/vendor/maplibre/maplibre-gl-csp.js"></script>
<script src="/static/course.js"></script>
<script src="/static/course-edit.js"></script>"""
    return _map_page(shell(g.principal, body, active="meets", wide=True), geolocation=True)


@bp.post("/meets/<int:mid>/course")
@login_required
def course_save(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    if m["sport"] not in ("xc", "road"):
        abort(404)
    raw = request.get_data(cache=False) or b""
    if len(raw) > 400_000:
        return jsonify(error="Course is too large to save."), 413
    try:
        doc = clean(json.loads(raw or b"null"))
    except ValueError as e:
        return jsonify(error=f"Couldn't save the course: {e}."), 400
    conn = db.connect()
    conn.execute("UPDATE meets SET course_json=? WHERE id=?", (json.dumps(doc), mid))
    conn.commit()
    conn.close()
    return jsonify(ok=True, courses=len(doc["courses"]))


# ------------------------------------------------------------------ public viewer
@bp.get("/r/<token>/course")
def course_view(token):
    from .xc import _meet_by_token
    m = _meet_by_token(token)
    data = load_course(m)
    if not has_course(m):
        abort(404)
    data["courses"] = [c for c in data["courses"] if len(c.get("points") or []) >= 2]
    cfg = _config(data=data, results=f"/r/{token}", meetName=m["name"])
    html = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#0a1728">
<title>{escape(m['name'])} — Course map · XCTimer</title>
<link rel="stylesheet" href="/static/vendor/maplibre/maplibre-gl.css">
<link rel="stylesheet" href="/static/course.css">
</head><body class="cv">
<div id="cv-map"></div>
<div id="cv-loading" class="cv-loading"><div class="cv-spin"></div>Loading the course…</div>
<header class="cv-top">
  <a class="cv-back" href="/r/{escape(token)}">‹ Results</a>
  <div class="cv-title">{escape(m['name'])}<small id="cv-sub"></small></div>
</header>
<div id="cv-chips" class="cv-chips"></div>
<div id="cv-toast" class="cv-toast" aria-live="polite"></div>
<footer class="cv-bottom">
  <div id="cv-stats" class="cv-stats"></div>
  <div class="cv-btns">
    <button type="button" id="cv-skip">Skip ⏭</button>
    <button type="button" id="cv-replay" hidden>▶ Replay fly-over</button>
  </div>
</footer>
<canvas id="cv-confetti" aria-hidden="true"></canvas>
<script type="application/json" id="cv-config">{cfg}</script>
<script src="/static/vendor/maplibre/maplibre-gl-csp.js"></script>
<script src="/static/vendor/confetti/confetti.browser.min.js"></script>
<script src="/static/course.js"></script>
<script src="/static/course-view.js"></script>
</body></html>"""
    return _map_page(html)
