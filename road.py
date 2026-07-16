"""Community road-race world: Organizers (a tenant separate from school districts),
their race-director logins, and Events. An event is a `meets` row owned by an
organizer (district_id NULL, sport='road') — so it reuses the whole timing/results
engine, minus schools, rosters, and PII.
"""
import re
import secrets

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort

from . import db
from .auth import login_required, role_required, create_user, send_setup_email
from .ui import shell

bp = Blueprint("road", __name__)


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "org"


def _organizer(oid):
    conn = db.connect()
    o = conn.execute("SELECT * FROM organizers WHERE id=?", (oid,)).fetchone()
    conn.close()
    return o


def _resolve_org():
    """The organizer the current principal is acting in, or None."""
    p = g.principal
    if getattr(p, "is_race_director", False):
        return p.organizer_id
    if p.is_super:
        raw = request.args.get("org") or request.form.get("org")
        return int(raw) if raw and raw.isdigit() else None
    return None


# ------------------------------- Organizers (super admin) -------------------------------
@bp.get("/organizers")
@role_required("super_admin")
def list_organizers():
    conn = db.connect()
    orgs = conn.execute("SELECT * FROM organizers ORDER BY name").fetchall()
    dirs = conn.execute(
        "SELECT id, email, name, role, organizer_id, setup_token FROM users "
        "WHERE role='race_director' ORDER BY email").fetchall()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT organizer_id, COUNT(*) FROM meets WHERE organizer_id IS NOT NULL "
        "GROUP BY organizer_id").fetchall()}
    conn.close()
    dir_by_org = {}
    for u in dirs:
        dir_by_org.setdefault(u["organizer_id"], []).append(u)

    cards = []
    for o in orgs:
        dl = "".join(
            f'<li>{escape(u["name"] or u["email"])} '
            f'<span class="muted">{escape(u["email"])}'
            f'{" · invite pending" if u["setup_token"] else ""}</span></li>'
            for u in dir_by_org.get(o["id"], [])) or '<li class="muted">No race directors yet.</li>'
        cards.append(
            f'<div class="card"><div style="display:flex;justify-content:space-between;'
            f'align-items:center;flex-wrap:wrap;gap:.5rem">'
            f'<h2 style="margin:0">🏁 {escape(o["name"])}</h2>'
            f'<a class="btn ghost" href="/events?org={o["id"]}">Events '
            f'({counts.get(o["id"], 0)}) →</a></div>'
            f'<h3 style="margin:.8rem 0 .3rem">Race directors</h3><ul style="margin:.2rem 0">{dl}</ul>'
            f'<form method="post" action="/organizers/{o["id"]}/directors" class="row" '
            f'style="gap:.5rem;flex-wrap:wrap;margin-top:.4rem">'
            f'<div><label>Director email</label><input name="email" type="email" required></div>'
            f'<div><label>Name</label><input name="name"></div>'
            f'<div style="display:flex;align-items:flex-end">'
            f'<button type="submit">+ Add race director</button></div></form></div>')

    body = (
        '<h1>Organizers</h1>'
        '<p class="muted">Community race organizers. Each runs its own road events '
        '(5K, 10K, half) with participants who register directly — no schools or rosters.</p>'
        '<div class="card"><h2>New organizer</h2>'
        '<form method="post" action="/organizers" class="row" style="gap:.6rem">'
        '<div><label>Name</label><input name="name" placeholder="e.g. Bear Lake Events" required></div>'
        '<div style="display:flex;align-items:flex-end"><button type="submit">Create</button></div>'
        '</form></div>'
        + ("".join(cards) or '<div class="card muted">No organizers yet.</div>'))
    return shell(g.principal, body, active="organizers")


@bp.post("/organizers")
@role_required("super_admin")
def create_organizer():
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    conn = db.connect()
    slug, base, n = _slugify(name), _slugify(name), 2
    while conn.execute("SELECT 1 FROM organizers WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    conn.execute("INSERT INTO organizers (name, slug) VALUES (?,?)", (name, slug))
    conn.commit()
    conn.close()
    return redirect("/organizers")


@bp.post("/organizers/<int:oid>/directors")
@role_required("super_admin")
def add_director(oid):
    if not _organizer(oid):
        abort(404)
    email = (request.form.get("email") or "").strip().lower()
    name = (request.form.get("name") or "").strip() or None
    if "@" not in email:
        abort(400)
    try:
        _uid, token = create_user(email, "race_director", organizer_id=oid, name=name)
    except Exception:  # duplicate email etc.
        return redirect("/organizers")
    send_setup_email(email, token)
    return redirect("/organizers")


# ------------------------------- Events -------------------------------
@bp.get("/events")
@role_required("super_admin", "race_director")
def list_events():
    p = g.principal
    oid = _resolve_org()
    conn = db.connect()
    # Super with no organizer chosen: show a picker.
    if oid is None and p.is_super:
        orgs = conn.execute("SELECT * FROM organizers ORDER BY name").fetchall()
        conn.close()
        picks = "".join(f'<li><a href="/events?org={o["id"]}">{escape(o["name"])}</a></li>'
                        for o in orgs) or '<li class="muted">No organizers yet.</li>'
        body = ('<h1>Events</h1><p class="muted">Pick an organizer to manage its events '
                '(<a href="/organizers">manage organizers</a>).</p>'
                f'<div class="card"><ul>{picks}</ul></div>')
        return shell(p, body, active="events")
    org = conn.execute("SELECT * FROM organizers WHERE id=?", (oid,)).fetchone()
    if not org:
        conn.close()
        abort(404)
    rows = conn.execute(
        "SELECT * FROM meets WHERE organizer_id=? ORDER BY date DESC, name", (oid,)).fetchall()
    conn.close()

    trs = "".join(
        f'<tr><td><b><a href="/meets/{m["id"]}">{escape(m["name"])}</a></b></td>'
        f'<td>{escape(m["date"] or "")}</td></tr>' for m in rows)
    table = (f'<div class="card"><table><tr><th>Event</th><th>Date</th></tr>{trs}</table></div>'
             if rows else '<div class="card muted">No events yet — create one below.</div>')
    org_field = f'<input type="hidden" name="org" value="{oid}">' if p.is_super else ""
    body = (
        f'<h1>{escape(org["name"])} — Events</h1>'
        + ('<p class="muted"><a href="/organizers">← Organizers</a></p>' if p.is_super else '')
        + table
        + '<div class="card"><h2>New event</h2>'
        + f'<form method="post" action="/events" class="row" style="gap:.6rem">{org_field}'
        + '<div><label>Name</label><input name="name" placeholder="e.g. Summer Classic" required></div>'
        + '<div style="max-width:180px"><label>Date</label><input name="date" type="date"></div>'
        + '<div style="display:flex;align-items:flex-end"><button type="submit">Create event</button>'
        + '</div></form></div>')
    return shell(p, body, active="events")


@bp.post("/events")
@role_required("super_admin", "race_director")
def create_event():
    oid = _resolve_org()
    if oid is None or not _organizer(oid):
        abort(400)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    date = (request.form.get("date") or "").strip() or None
    conn = db.connect()
    mid = conn.execute(
        "INSERT INTO meets (organizer_id, sport, name, date, public_token, team_scoring) "
        "VALUES (?,?,?,?,?,0)",
        (oid, "road", name, date, secrets.token_urlsafe(8))).lastrowid
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")
