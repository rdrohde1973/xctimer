"""Phone timing app (xctimer.com/phone).

Coaches log in and see only the meets they attend and the events they're part of;
a no-login QR (meets.py /t/<token>) drops a helper straight into one meet's timing.
Both land here. XC meets time via the race console; track via the per-event grid.
"""
from markupsafe import escape
from flask import Blueprint, g, redirect

from . import db
from .meets import load_meet, can_record_meet
from .ui import shell

bp = Blueprint("phone", __name__)

BTN = ('display:block;padding:1rem 1.1rem;margin:.5rem 0;font-size:1.1rem;'
       'text-align:left;border-radius:12px')


def _phone_shell(principal, body):
    return shell(principal, body, active="phone")


def _meet_card(m):
    p = g.principal
    conn = db.connect()
    body = [f'<p class="muted"><a href="/phone">← Meets</a></p>',
            f'<h1>{"🏃" if m["sport"]=="xc" else "🏟️"} {escape(m["name"])}</h1>',
            f'<p class="sub">{escape(m["date"] or "")}</p>']
    if m["sport"] == "xc":
        races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (m["id"],)).fetchall()
        body.append('<h2>Heats — tap to time</h2>')
        for r in races:
            status = "ended" if r["stop_time"] else ("running" if r["start_time"] else "not started")
            body.append(f'<a class="btn" style="{BTN}" href="/races/{r["id"]}/console">'
                        f'⏱ {escape(r["name"])} <span class="muted">· {r["capture_mode"]} · {status}</span></a>')
        if not races:
            body.append('<p class="muted">No heats yet.</p>')
    else:
        # Track: events the principal is part of (coach -> their school's entries)
        if p.role == "coach" and not p.meet_scope and p.school_ids():
            ids = p.school_ids()
            q = ",".join("?" * len(ids))
            mes = conn.execute(
                f"SELECT DISTINCT me.id, e.name AS ename, me.gender, me.grade, e.sort "
                f"FROM meet_events me JOIN events e ON e.id=me.event_id "
                f"JOIN entries en ON en.meet_event_id=me.id "
                f"WHERE me.meet_id=? AND en.school_id IN ({q}) ORDER BY e.sort, me.gender, me.grade",
                (m["id"], *ids)).fetchall()
            scoped = True
        else:
            mes = conn.execute(
                "SELECT me.id, e.name AS ename, me.gender, me.grade, e.sort "
                "FROM meet_events me JOIN events e ON e.id=me.event_id "
                "WHERE me.meet_id=? ORDER BY e.sort, me.gender, me.grade", (m["id"],)).fetchall()
            scoped = False
        hdr = "Events you're in" if scoped else "Events"
        body.append(f'<h2>{hdr} — tap to record</h2>')
        for me in mes:
            div = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open") + (f" G{me['grade']}" if me["grade"] else "")
            body.append(f'<a class="btn" style="{BTN}" href="/meet-events/{me["id"]}">'
                        f'{escape(me["ename"])} <span class="muted">· {div}</span></a>')
        if not mes:
            body.append('<p class="muted">No events for you yet — ask the host to assign your athletes.</p>')
    conn.close()
    return _phone_shell(g.principal, "".join(body))


@bp.get("/phone")
def phone_home():
    p = getattr(g, "principal", None)
    if not p:
        return redirect("/login?next=/phone")
    if p.meet_scope:                       # no-login QR: straight into that meet
        return _meet_card(load_meet(p.meet_scope))
    conn = db.connect()
    rows = conn.execute("SELECT * FROM meets ORDER BY date DESC, id DESC").fetchall()
    conn.close()
    meets = [m for m in rows if can_record_meet(m)]
    body = ['<h1>📱 Phone timing</h1>',
            '<p class="sub">Pick a meet, then a heat/event to time or record.</p>']
    for m in meets:
        icon = "🏃" if m["sport"] == "xc" else "🏟️"
        body.append(f'<a class="btn" style="{BTN}" href="/phone/meet/{m["id"]}">'
                    f'{icon} {escape(m["name"])} <span class="muted">· {escape(m["date"] or "")}</span></a>')
    if not meets:
        body.append('<div class="card muted">No meets available to you right now.</div>')
    return _phone_shell(p, "".join(body))


@bp.get("/phone/meet/<int:mid>")
def phone_meet(mid):
    p = getattr(g, "principal", None)
    if not p:
        return redirect(f"/login?next=/phone/meet/{mid}")
    m = load_meet(mid)
    if not can_record_meet(m):
        from flask import abort
        abort(403)
    return _meet_card(m)
