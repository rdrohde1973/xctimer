"""Phone timing app (xctimer.com/phone).

Coaches log in and see only the meets they attend and the events they're part of;
a no-login QR (meets.py /t/<token>) drops a helper straight into one meet's timing.
Both land here. XC meets time via the race console; track via the per-event grid.
"""
import io
import json
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
    return shell(principal, body, active="phone", bare=True)


def _meet_card(m):
    conn = db.connect()
    if m["sport"] == "xc":
        body = [f'<p class="muted"><a href="/phone">← Meets</a></p>',
                f'<h1>🏃 {escape(m["name"])}</h1><p class="sub">{escape(m["date"] or "")}</p>',
                '<h2>Heats — tap to time</h2>']
        races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (m["id"],)).fetchall()
        for r in races:
            status = "ended" if r["stop_time"] else ("running" if r["start_time"] else "not started")
            body.append(f'<a class="btn" style="{BTN}" href="/races/{r["id"]}/console">'
                        f'⏱ {escape(r["name"])} <span class="muted">· {r["capture_mode"]} · {status}</span></a>')
        if not races:
            body.append('<p class="muted">No heats yet.</p>')
        html = "".join(body)
    else:
        html = _track_timer(conn, m)
    conn.close()
    return _phone_shell(g.principal, html)


def _track_timer(conn, m):
    """Two-tab Track Timer: Time race (event/heat pickers -> tap console) + Scan sheet."""
    tap_q = ",".join("?" * len(TAP_EVENTS))
    events = conn.execute(
        f"SELECT me.id, e.name AS ename, me.gender, me.grade FROM meet_events me "
        f"JOIN events e ON e.id=me.event_id WHERE me.meet_id=? AND e.name IN ({tap_q}) "
        f"ORDER BY e.sort, me.gender, me.grade", (m["id"], *TAP_EVENTS)).fetchall()
    evdata, ev_opts = {}, ['<option value="">— pick event —</option>']
    for ev in events:
        heats = [r[0] for r in conn.execute(
            "SELECT DISTINCT heat FROM entries WHERE meet_event_id=? AND heat IS NOT NULL "
            "ORDER BY heat", (ev["id"],)).fetchall()]
        gword = {"M": "Boys", "F": "Girls"}.get(ev["gender"], "")
        gr = f"{ev['grade']}th Grade " if ev["grade"] else ""
        label = f"{gr}{gword + ' ' if gword else ''}{ev['ename']}".strip()
        evdata[str(ev["id"])] = {"label": label, "heats": heats}
        ev_opts.append(f'<option value="{ev["id"]}">{escape(label)}</option>')
    # meet switcher (track meets the user can time)
    meet_opts = []
    for mm in conn.execute("SELECT * FROM meets WHERE district_id=? AND sport='track' "
                           "ORDER BY date DESC, id DESC", (m["district_id"],)).fetchall():
        if can_record_meet(mm):
            sel = "selected" if mm["id"] == m["id"] else ""
            meet_opts.append(f'<option value="{mm["id"]}" {sel}>{escape(mm["name"])}</option>')

    return f"""
<h1>🏅 Track Timer</h1>
<div class="seg">
  <button id="seg-scan" class="ghost" onclick="segTab('scan')">📷 Scan sheet</button>
  <button id="seg-time" onclick="segTab('time')">⏱ Time race</button>
</div>

<div class="card" id="tab-time">
  <h2>Time a race</h2>
  <p class="sub">For 800m, 1600m, 3200m &amp; 4×400m — start the clock and tap each runner as they finish.</p>
  <label>Meet</label>
  <select onchange="if(this.value)location.href='/phone/meet/'+this.value">{''.join(meet_opts)}</select>
  <label>Event</label>
  <select id="tev" onchange="fillHeats()">{''.join(ev_opts)}</select>
  <label>Heat / section</label>
  <select id="tht" onchange="upd()"></select>
  <button id="startbtn" onclick="startRace()" disabled style="width:100%;margin-top:1rem;padding:.8rem">▶ Start race</button>
</div>

<div class="card" id="tab-scan" style="display:none">
  <h2>Scan a heat sheet</h2>
  <p class="sub">Take a photo of a marked-up heat sheet. The results are read and posted to that heat.</p>
  <label>Event</label>
  <select id="sev">{''.join(ev_opts)}</select>
  <label>Photo of the sheet</label>
  <input type="file" id="scanf" accept="image/*" capture="environment" onchange="doScan()">
  <p class="muted">Reads automatically once you take the photo.</p>
  <div id="scanout"></div>
</div>

<style>
.seg{{display:flex;gap:.6rem;margin:.4rem 0 1rem}}
.seg button{{flex:1;padding:1rem;font-size:1.05rem}}
</style>
<script>
const EV={json.dumps(evdata)};
function segTab(t){{
  document.getElementById('tab-time').style.display = t==='time'?'':'none';
  document.getElementById('tab-scan').style.display = t==='scan'?'':'none';
  document.getElementById('seg-time').className = t==='time'?'':'ghost';
  document.getElementById('seg-scan').className = t==='scan'?'':'ghost';
}}
function fillHeats(){{
  const ev=document.getElementById('tev').value, ht=document.getElementById('tht');
  ht.innerHTML='';
  const d=EV[ev];
  if(!d){{ht.innerHTML='<option value="">— pick an event first —</option>';upd();return;}}
  if(!d.heats.length){{ht.innerHTML='<option value="">no heats — draw them first</option>';upd();return;}}
  d.heats.forEach(function(h){{ht.innerHTML+='<option value="'+h+'">Heat '+h+'</option>';}});
  upd();
}}
function upd(){{
  const ev=document.getElementById('tev').value, ht=document.getElementById('tht').value;
  document.getElementById('startbtn').disabled = !(ev && ht);
}}
function startRace(){{
  const ev=document.getElementById('tev').value, ht=document.getElementById('tht').value;
  if(ev&&ht) location.href='/meet-events/'+ev+'/time?heat='+ht;
}}
async function doScan(){{
  const ev=document.getElementById('sev').value;
  const f=document.getElementById('scanf').files[0];
  if(!ev){{alert('Pick the event first');return;}}
  if(!f)return;
  document.getElementById('scanout').innerHTML='<p class="muted">Reading…</p>';
  const fd=new FormData(); fd.append('image',f);
  const r=await fetch('/meet-events/'+ev+'/scan',{{method:'POST',body:fd}});
  const j=await r.json();
  if(!r.ok||!(j.marks||[]).length){{document.getElementById('scanout').innerHTML='<p class="msg err">'+esc((j.error||'No marks read'))+'</p>';return;}}
  let h='<p class="muted">Review, then post.</p><table><tr><th>Bib</th><th>Mark</th></tr>';
  j.marks.forEach(function(m,i){{h+='<tr><td><input id="sb'+i+'" value="'+esc(m.bib==null?'':m.bib)+'" style="width:70px"></td>'
    +'<td><input id="sm'+i+'" value="'+esc(m.mark==null?'':m.mark)+'" style="width:120px"></td></tr>';}});
  h+='</table><button onclick="postScan('+j.marks.length+','+ev+')" style="margin-top:.6rem">Post to this event</button>';
  document.getElementById('scanout').innerHTML=h;
}}
async function postScan(n,ev){{
  const marks=[];
  for(let i=0;i<n;i++){{const b=document.getElementById('sb'+i).value.trim();const mk=document.getElementById('sm'+i).value.trim();if(b&&mk)marks.push({{bib:b,mark:mk}});}}
  try{{const j=await jpost('/meet-events/'+ev+'/scan/post',{{marks}});alert('Posted '+j.applied+' marks'+(j.unmatched&&j.unmatched.length?'; unmatched: '+j.unmatched.join(', '):''));}}
  catch(e){{alert(e.message);}}
}}
</script>"""


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
            '<p class="sub">Pick a meet, then a heat or event to time.</p>']
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
