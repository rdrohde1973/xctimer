"""Multi-tenancy: district scoping, the Super-Admin switcher, and scope guards.

district_id is the OUTERMOST guard on every scoped endpoint (handoff §4).
- Super Admin: active district held in the signed Flask session; None = all districts.
- Everyone else: locked to their own district_id; no switcher.
"""
from flask import Blueprint, g, session, redirect, request, abort

from . import db

bp = Blueprint("tenancy", __name__)


def all_districts():
    conn = db.connect()
    rows = conn.execute("SELECT * FROM districts ORDER BY name").fetchall()
    conn.close()
    return rows


def active_district_id():
    """The district the current principal is operating in.

    Super Admin: session-selected (or None => all districts).
    Others: their fixed district_id.
    """
    p = getattr(g, "principal", None)
    if not p:
        return None
    if p.is_super:
        return session.get("active_district_id")
    return p.district_id


def require_district(district_id):
    """Abort unless the principal may act within `district_id`."""
    p = getattr(g, "principal", None)
    if not p:
        abort(403)
    if p.is_super:
        return
    if p.district_id != district_id:
        abort(403)


def scoped_district_or_403():
    """Return the district_id to write into new rows, or 403 if unresolved.

    Super Admin must have a district selected to create district-scoped data.
    """
    did = active_district_id()
    if did is None:
        abort(400)
    return did


@bp.post("/switch-district")
def switch_district():
    p = getattr(g, "principal", None)
    if not p or not p.is_super:
        abort(403)
    raw = (request.form.get("district_id") or "").strip()
    if raw == "":
        session.pop("active_district_id", None)
    else:
        session["active_district_id"] = int(raw)
    return redirect(request.referrer or "/dashboard")
