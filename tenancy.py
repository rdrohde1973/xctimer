"""Multi-tenancy: district scoping, the Super-Admin switcher, and scope guards.

district_id is the OUTERMOST guard on every scoped endpoint (handoff §4).
- Super Admin: active district held in the signed Flask session; None = all districts.
- Everyone else: locked to their own district_id; no switcher.
"""
import json

from flask import Blueprint, g, session, redirect, request, abort

from . import db

bp = Blueprint("tenancy", __name__)


def all_districts():
    conn = db.connect()
    rows = conn.execute("SELECT * FROM districts ORDER BY name").fetchall()
    conn.close()
    return rows


# Grades a district runs. Unset = the junior-high default. A district with a high school sets
# its own list on the Districts page (settings_json["grades"]); nothing else is grade-limited --
# rosters, XC heats and results already take any grade number.
DEFAULT_GRADES = (6, 7, 8, 9)


def parse_grades(text):
    """'7-12', '9,10,11,12' or '6-8, 10' -> sorted unique ints within 1..12. None if nothing
    valid was given or anything in it is not a grade."""
    out = set()
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip().replace("–", "-").replace("—", "-")
        if not part:
            continue
        lo, sep, hi = part.partition("-")
        try:
            lo = int(lo.strip())
            hi = int(hi.strip()) if sep else lo
        except ValueError:
            return None
        if not (1 <= lo <= hi <= 12):
            return None
        out.update(range(lo, hi + 1))
    return sorted(out) or None


def custom_grades(district_id):
    """The district's own grade list, or None when it uses the default."""
    if not district_id:
        return None
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (district_id,)).fetchone()
    conn.close()
    try:
        v = json.loads((d["settings_json"] if d else None) or "{}").get("grades")
    except (ValueError, TypeError):
        return None
    if not isinstance(v, list):
        return None
    return parse_grades(",".join(str(x) for x in v))


def district_grades(district_id):
    """Grades to offer when building events for this district (lowest first)."""
    return custom_grades(district_id) or list(DEFAULT_GRADES)


def grades_span(grades):
    """[7, 8, 9, 10, 11, 12] -> '7-12'; a list with gaps is spelled out ('6, 8, 9')."""
    grades = list(grades)
    if not grades:
        return ""
    if len(grades) > 1 and grades == list(range(grades[0], grades[-1] + 1)):
        return f"{grades[0]}-{grades[-1]}"
    return ", ".join(str(g) for g in grades)


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
