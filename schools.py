"""Schools management. Phase 1: CRUD + bib blocks (district-scoped).

Phase 2 adds athlete rosters, AI import, Google Sheet sync, bib stickers/lists,
and bib check — see the module TODO history and handoff §8.
"""
from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort

from . import db
from .auth import login_required, role_required
from .tenancy import active_district_id, require_district, scoped_district_or_403, all_districts
from .ui import shell

bp = Blueprint("schools", __name__)


def _districts_for_switcher():
    p = g.principal
    return all_districts() if p.is_super else None


@bp.get("/schools")
@role_required("super_admin", "district_admin")
def list_schools():
    did = active_district_id()
    conn = db.connect()
    if did is None:  # super admin, all districts
        rows = conn.execute(
            "SELECT s.*, d.name AS dname FROM schools s "
            "JOIN districts d ON d.id=s.district_id ORDER BY d.name, s.name"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT s.*, NULL AS dname FROM schools s WHERE s.district_id=? ORDER BY s.name",
            (did,),
        ).fetchall()
    conn.close()

    show_d = did is None
    head = "<tr><th>School</th>" + ("<th>District</th>" if show_d else "") + \
           "<th>Bib block</th><th></th></tr>"
    body_rows = []
    for s in rows:
        bib = f'{s["bib_start"]}–{s["bib_end"]}' if s["bib_start"] else '<span class="muted">—</span>'
        dcol = f'<td>{escape(s["dname"])}</td>' if show_d else ""
        body_rows.append(
            f'<tr><td><b>{escape(s["name"])}</b></td>{dcol}<td>{bib}</td>'
            f'<td style="text-align:right">'
            f'<form class="inline" method="post" action="/schools/{s["id"]}/delete" '
            f'onsubmit="return confirm(\'Delete {escape(s["name"])}?\')">'
            f'<button class="danger" type="submit">Delete</button></form></td></tr>'
        )
    table = (f'<div class="card"><table>{head}{"".join(body_rows)}</table></div>'
             if rows else '<div class="card muted">No schools yet.</div>')

    create_hint = ""
    if g.principal.is_super and did is None:
        create_hint = ('<p class="muted">Pick a district in the header to add a school.</p>')
        form = ""
    else:
        form = """
<div class="card"><h2>Add a school</h2>
<form method="post" action="/schools">
  <label>Name</label><input name="name" required>
  <div class="row">
    <div><label>Bib start</label><input name="bib_start" type="number" inputmode="numeric"></div>
    <div><label>Bib end</label><input name="bib_end" type="number" inputmode="numeric"></div>
  </div>
  <label>Logo path (optional)</label><input name="logo_path" placeholder="static/logos/....png">
  <button type="submit" style="margin-top:1rem">Add school</button>
</form></div>"""

    body = f"<h1>Schools</h1><p class='sub'>Manage schools and their bib blocks.</p>{create_hint}{table}{form}"
    return shell(g.principal, body, active="schools",
                 active_district=did, districts=_districts_for_switcher())


@bp.post("/schools")
@role_required("super_admin", "district_admin")
def create_school():
    did = scoped_district_or_403()
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)

    def _int(v):
        v = (v or "").strip()
        return int(v) if v.isdigit() else None

    conn = db.connect()
    conn.execute(
        "INSERT INTO schools (district_id, name, bib_start, bib_end, logo_path) VALUES (?,?,?,?,?)",
        (did, name, _int(request.form.get("bib_start")), _int(request.form.get("bib_end")),
         (request.form.get("logo_path") or "").strip() or None),
    )
    conn.commit()
    conn.close()
    return redirect("/schools")


@bp.post("/schools/<int:sid>/delete")
@role_required("super_admin", "district_admin")
def delete_school(sid):
    conn = db.connect()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (sid,)).fetchone()
    if not s:
        conn.close()
        abort(404)
    require_district(s["district_id"])
    conn.execute("DELETE FROM user_schools WHERE school_id=?", (sid,))
    conn.execute("DELETE FROM schools WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return redirect("/schools")
