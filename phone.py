"""Phone timing app (xctimer.com/phone).

Coaches log in and see only the meets they attend and the events they're part of;
a no-login QR (meets.py /t/<token>) drops a helper straight into one meet's timing.
Both land here. XC meets time via the race console; track via the per-event grid.
"""
import io
import os

from markupsafe import escape
from flask import Blueprint, g, redirect, request, Response

from . import db
from .meets import load_meet, can_record_meet
from .ui import shell

bp = Blueprint("phone", __name__)

BTN = ('display:block;padding:1rem 1.1rem;margin:.5rem 0;font-size:1.1rem;'
       'text-align:left;border-radius:12px')

# Events timed by tapping finishers at the line (distance + 4x400). Sprints and
# field events are recorded from sheets/lane entry, not the phone tap timer.
TAP_EVENTS = ("800m", "1600m", "3200m", "4x400m Relay")


def _phone_url():
    base = os.environ.get("XC_PUBLIC_URL") or request.host_url.rstrip("/")
    return f"{base}/phone"


def _phone_shell(principal, body):
    return shell(principal, body, active="phone")


def _meet_card(m):
    p = g.principal
    conn = db.connect()
    body = [f'<p class="muted"><a href="/phone">← Meets</a></p>',
            f'<h1>{"🏃" if m["sport"]=="xc" else "🎽"} {escape(m["name"])}</h1>',
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
        # Track: only the tap-timed events (distance + 4x400), and for a coach only
        # the ones their school is entered in.
        tap_q = ",".join("?" * len(TAP_EVENTS))
        if p.role == "coach" and not p.meet_scope and p.school_ids():
            ids = p.school_ids()
            q = ",".join("?" * len(ids))
            mes = conn.execute(
                f"SELECT DISTINCT me.id, e.name AS ename, me.gender, me.grade, e.sort "
                f"FROM meet_events me JOIN events e ON e.id=me.event_id "
                f"JOIN entries en ON en.meet_event_id=me.id "
                f"WHERE me.meet_id=? AND en.school_id IN ({q}) AND e.name IN ({tap_q}) "
                f"ORDER BY e.sort, me.gender, me.grade", (m["id"], *ids, *TAP_EVENTS)).fetchall()
            scoped = True
        else:
            mes = conn.execute(
                f"SELECT me.id, e.name AS ename, me.gender, me.grade, e.sort "
                f"FROM meet_events me JOIN events e ON e.id=me.event_id "
                f"WHERE me.meet_id=? AND e.name IN ({tap_q}) "
                f"ORDER BY e.sort, me.gender, me.grade", (m["id"], *TAP_EVENTS)).fetchall()
            scoped = False
        hdr = "Your distance/relay events" if scoped else "Distance & 4x400 — tap to time"
        body.append(f'<h2>{hdr}</h2>')
        for me in mes:
            div = {"M": "Boys", "F": "Girls"}.get(me["gender"], "Open") + (f" G{me['grade']}" if me["grade"] else "")
            body.append(f'<a class="btn" style="{BTN}" href="/meet-events/{me["id"]}">'
                        f'{escape(me["ename"])} <span class="muted">· {div}</span></a>')
        if not mes:
            body.append('<p class="muted">No distance/relay events to time here yet.</p>')
    conn.close()
    return _phone_shell(g.principal, "".join(body))


def _install_card():
    url = _phone_url()
    return f"""
<div class="card"><h2>📱 The app on your phone</h2>
<p class="muted">Coaches scan this (or open the link) on their phone, sign in with their
coach email, and add it to their home screen. Same link for everyone, every meet.</p>
<div style="display:flex;gap:1.2rem;flex-wrap:wrap;align-items:flex-start">
  <img src="/phone/qr.png" width="150" height="150"
       style="background:#fff;padding:8px;border-radius:8px">
  <div style="flex:1;min-width:250px">
    <p style="margin:0 0 .3rem">Or open <code style="background:var(--panel2);padding:.25rem .5rem;border-radius:8px">{escape(url)}</code></p>
    <ol class="muted" style="margin-top:.7rem;line-height:1.9">
      <li>Open the link on your phone (or scan the QR).</li>
      <li>Sign in with your coach email.</li>
      <li><b>iPhone:</b> Share → <b>Add to Home Screen</b>. &nbsp;<b>Android:</b> ⋮ menu → <b>Install app</b>.</li>
      <li>Open it on meet day to enter your athletes and results.</li>
    </ol>
  </div>
</div></div>"""


@bp.get("/phone/qr.png")
def phone_qr():
    import qrcode
    img = qrcode.make(_phone_url())
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), mimetype="image/png")


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
            '<p class="sub">Pick a meet, then a heat/event to time or record.</p>',
            _install_card(),
            '<h2>Your meets</h2>']
    for m in meets:
        icon = "🏃" if m["sport"] == "xc" else "🎽"
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
