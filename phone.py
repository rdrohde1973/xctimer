"""Phone timing app (xctimer.com/phone).

Coaches log in and see only the meets they can record; a no-login QR
(meets.py /t/<token>) drops a helper straight into one meet's timing. The XC
flow mirrors the old app: a full-screen "Pick a heat to run" list, then a
full-screen tap console (START -> FINISHER / UNDO / STOP). Track meets open the
two-tab Track Timer. All screens drive the same /races/<rid>/* JSON API, so a
phone tapping and a desktop scanning bibs share one race.
"""
import io
import json
import os

from markupsafe import escape
from flask import Blueprint, g, redirect, request, Response, abort

from . import db
from .meets import load_meet, can_record_meet
from .ui import shell, HEAD_EXTRA, CSS, JS, BRAND_HTML, LOGO_APP_URL, GUN_CONTROLS_HTML, GUN_JS

bp = Blueprint("phone", __name__)

# Events timed by tapping finishers at the line (distance + 4x400). Sprints and
# field events are recorded from sheets/lane entry, not the phone tap timer.
TAP_EVENTS = ("800m", "1600m", "3200m", "4x400m Relay")
LANE_EVENTS = ("100m", "200m", "400m", "4x100m Relay")   # laned -> one volunteer per lane


def _phone_url():
    base = os.environ.get("XC_PUBLIC_URL") or request.host_url.rstrip("/")
    return f"{base}/phone"


# ------------------------------ full-screen doc ------------------------------
def _phone_doc(title, body, extra_css=""):
    """Standalone full-screen page (no app shell chrome) for the phone timer."""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>{escape(title)} · XCTimer</title>{HEAD_EXTRA}<style>{CSS}{extra_css}</style></head>
<body class="phone">{body}<script>{JS}</script></body></html>"""


def _district_brand(p):
    """District logo for the picker header; XCTimer wordmark when there's none."""
    did = getattr(p, "district_id", None)
    if did:
        conn = db.connect()
        r = conn.execute("SELECT logo_path FROM districts WHERE id=?", (did,)).fetchone()
        conn.close()
        if r and r["logo_path"]:
            return f'<span class="dchip"><img src="{r["logo_path"]}" alt=""></span>'
    return f'<img class="xclogo" src="{LOGO_APP_URL}" alt="XCTimer">'


PICK_CSS = """
body.phone{background:var(--bg);min-height:100vh;margin:0}
.pickhdr{text-align:center;padding:1.6rem 1rem .4rem}
.pickhdr .dchip{display:inline-flex;background:#f4f6f8;border-radius:14px;padding:.5rem .9rem}
.pickhdr .dchip img{max-width:280px;max-height:84px;object-fit:contain;display:block}
.pickhdr .wordmark{font-size:2rem;font-weight:800}
.pickhdr .xclogo{max-width:300px;max-height:120px;width:auto;border-radius:12px}
.pickhdr h1{font-size:1.4rem;margin:1rem 0 .2rem}
.pickhdr .who{color:var(--mut);font-size:.92rem}
.meet{margin:0 .8rem 1rem;border:1px solid var(--line);border-radius:14px;overflow:hidden}
.meet .mh{background:var(--panel);padding:.7rem 1rem;font-weight:700;
  display:flex;justify-content:space-between;align-items:baseline;gap:.6rem}
.meet .mh small{color:var(--mut);font-weight:400}
.heat{display:flex;justify-content:space-between;align-items:center;gap:.6rem;
  padding:1rem;border-top:1px solid var(--line);color:var(--fg);font-size:1.1rem}
.heat:hover{background:var(--panel2);text-decoration:none}
.heat .hn small{color:var(--mut);font-size:.8rem}
.heat.empty{color:var(--dim);font-size:.95rem}
.st{font-size:.72rem;padding:.22rem .6rem;border-radius:999px;text-transform:capitalize;white-space:nowrap}
.st.ns{background:#2a3a4d;color:#b9c8d8}
.st.run{background:rgba(63,191,127,.2);color:var(--ok)}
.st.end{background:#22303f;color:#8ea6c0}
.st.go{background:rgba(234,106,45,.2);color:var(--acc)}
.lo{text-align:center;margin:1.6rem 0 2.4rem}
.lo button{background:transparent;color:var(--mut);border:0;text-decoration:underline;
  font:inherit;cursor:pointer}
"""


@bp.get("/phone")
def phone_home():
    """Pick a heat to run — every meet the coach can record, grouped, with a
    ready/running/ended pill per heat (no-login QR is scoped to its one meet)."""
    p = getattr(g, "principal", None)
    if not p:
        return redirect("/login?next=/phone")
    conn = db.connect()
    if getattr(p, "meet_scope", None):
        rows = conn.execute("SELECT * FROM meets WHERE id=?", (p.meet_scope,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM meets ORDER BY date DESC, id DESC").fetchall()
    meets = [m for m in rows if can_record_meet(m)]
    # No-login QR is locked to one meet — for a track meet, drop the helper straight
    # into the Track Timer instead of a one-tile "pick a meet" page.
    if getattr(p, "meet_scope", None) and len(meets) == 1 and meets[0]["sport"] == "track":
        conn.close()
        return redirect(f"/phone/meet/{meets[0]['id']}")
    groups = []
    for m in meets:
        if m["sport"] in ("xc", "road"):
            races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id",
                                 (m["id"],)).fetchall()
            noun = "events" if m["sport"] == "road" else "heats"
            heats = []
            for r in races:
                if r["stop_time"]:
                    cls, lbl = "end", "ended"
                elif r["start_time"]:
                    cls, lbl = "run", "running"
                else:
                    cls, lbl = "ns", "ready"
                heats.append(
                    f'<a class="heat" href="/phone/race/{r["id"]}">'
                    f'<span class="hn">{escape(r["name"])} <small>· {escape(r["capture_mode"])}</small></span>'
                    f'<span class="st {cls}">{lbl}</span></a>')
            inner = "".join(heats) or f'<div class="heat empty">No {noun} yet — add them in meet setup.</div>'
        else:
            inner = (f'<a class="heat" href="/phone/meet/{m["id"]}">'
                     f'<span class="hn">🎽 Track Timer</span><span class="st go">open</span></a>')
        groups.append(
            f'<div class="meet"><div class="mh"><span>{escape(m["name"])}</span>'
            f'<small>{escape(m["date"] or "")}</small></div>{inner}</div>')
    conn.close()
    who = escape(p.name or p.email or "")
    role = " · Admin" if getattr(p, "role", "") in ("super_admin", "district_admin") else ""
    body = (f'<div class="pickhdr">{_district_brand(p)}'
            f'<h1>Pick a heat to run</h1><div class="who">{who}{role}</div></div>'
            + ("".join(groups) or '<div class="meet"><div class="heat empty" '
               'style="border:0">No meets available to you right now.</div></div>')
            + '<form method="post" action="/logout" class="lo"><button>Log out</button></form>')
    return _phone_doc("Pick a heat", body, PICK_CSS)


# ------------------------------ full-screen tap console ------------------------------
TIMER_CSS = """
html,body.phone{height:100%}
body.phone{margin:0;display:flex;flex-direction:column;overflow:hidden;background:#08111d}
.tbar{display:flex;justify-content:space-between;align-items:center;background:#000;color:#fff;padding:.7rem 1rem}
.tcount{line-height:1.05}
.tcount span{font-size:1.5rem;font-weight:800}
.tcount small{display:block;font-size:.58rem;letter-spacing:.14em;color:#9aa}
.tclock{font-size:1.7rem;font-weight:800;font-variant-numeric:tabular-nums;letter-spacing:-.01em}
.subbar{display:flex;align-items:center;background:var(--panel);padding:.5rem 1rem;border-bottom:1px solid var(--line)}
.subbar .back{color:var(--link);font-weight:600;min-width:74px}
.subbar .rn{flex:1;text-align:center;font-weight:700}
.subbar .camlink{min-width:74px;text-align:right;color:var(--link);font-weight:700;text-decoration:none;font-size:1.1rem}
.tmain{flex:1;display:flex;flex-direction:column;padding:.8rem;min-height:0}
.bigbtn{border:0;border-radius:18px;color:#fff;font-weight:800;letter-spacing:.05em;cursor:pointer;width:100%}
.bigbtn:active{filter:brightness(1.15)}
.bigbtn.start{background:#2f7d32;flex:1;font-size:3rem}
.bigbtn.tap{background:#2f6db5;padding:2.3rem 0;font-size:2.4rem;margin-bottom:.6rem}
.scanbox{display:flex;flex-direction:column;gap:.6rem;margin-bottom:.6rem}
.scanbox input{font-size:1.7rem;text-align:center;padding:.7rem}
.flist{flex:1;overflow-y:auto;background:var(--panel2);border-radius:14px;padding:.2rem .3rem}
.flist .empty{color:var(--dim);text-align:center;padding:2.2rem 1rem}
.frow{display:flex;align-items:center;gap:.8rem;padding:.55rem .7rem;border-bottom:1px solid var(--line)}
.frow:last-child{border-bottom:0}
.frow .fp{font-weight:800;color:var(--acc);min-width:1.7rem}
.frow .ft{font-variant-numeric:tabular-nums;color:var(--mut);font-size:.9rem}
.frow .fw{flex:1;text-align:right;font-weight:600}
.banner{background:rgba(240,98,91,.15);color:var(--err);text-align:center;padding:.7rem;
  border-radius:10px;margin-bottom:.6rem;font-weight:600}
.ctrls{display:flex;gap:.6rem;padding:.7rem;padding-bottom:calc(.7rem + env(safe-area-inset-bottom));background:#08111d}
.ctl{flex:1;border:0;border-radius:14px;font-size:1.15rem;font-weight:700;padding:1rem;color:#fff;cursor:pointer}
.ctl.undo{background:#4a4a4a}
.ctl.stop{background:#c0392b}
.ctl:disabled{opacity:.4}
#pickbox{display:none;flex-direction:column;gap:.4rem;margin-bottom:.6rem}
#pickbox input{font-size:1.1rem;padding:.6rem;text-align:center}
#pickbox .ph{font-size:.72rem;letter-spacing:.12em;color:#9aa;text-transform:uppercase;text-align:center}
.plist{max-height:34vh;overflow-y:auto;background:var(--panel2);border-radius:12px}
.plist .pr{display:flex;justify-content:space-between;align-items:center;gap:.6rem;
  padding:.7rem .8rem;border-bottom:1px solid var(--line)}
.plist .pr:last-child{border-bottom:0}
.plist .pr .pnm{font-weight:700}
.plist .pr .pmeta{color:var(--mut);font-size:.82rem}
.plist .pr .pbib{color:var(--acc);font-weight:800;min-width:2.4rem;text-align:right}
.plist .empty{color:var(--dim);text-align:center;padding:1.6rem 1rem}
"""


@bp.get("/phone/race/<int:rid>")
def phone_race(rid):
    p = getattr(g, "principal", None)
    if not p:
        return redirect(f"/login?next=/phone/race/{rid}")
    conn = db.connect()
    r = conn.execute("SELECT * FROM races WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not r:
        abort(404)
    m = load_meet(r["meet_id"])
    if not can_record_meet(m):
        abort(403)
    body = f"""
<script src="/static/vendor/cv.js"></script>
<script src="/static/vendor/aruco.js"></script>
<div class="tbar">
  <div class="tcount"><span id="count">0</span><small>FINISHERS</small></div>
  <div id="clock" class="tclock">0:00:00</div>
</div>
<div class="subbar"><a href="/phone" class="back">‹ Heats</a>
  <span class="rn">{escape(r['name'])}</span>
  <a href="/races/{rid}/camera?phone=1" class="camlink" title="Time with the camera">📷</a></div>
<div class="tmain">
  <button id="startb" class="bigbtn start" onclick="startRace()">START</button>
  {GUN_CONTROLS_HTML}
  <button id="tapb" class="bigbtn tap" onclick="tap()" style="display:none">FINISHER</button>
  <div id="scanbox" class="scanbox" style="display:none">
    <input id="sbib" inputmode="numeric" autocomplete="off" placeholder="scan or type bib #"
      onkeydown="if(event.key==='Enter')rec()">
    <button class="bigbtn tap" onclick="rec()">RECORD</button>
  </div>
  <div id="pickbox">
    <div class="ph" id="pickhint">Tap a finisher above, then scan their bib tag or pick the name</div>
    <button id="scanToggle" onclick="toggleScan()"
      style="width:100%;padding:.7rem;margin:.2rem 0 .5rem;font-weight:700;border:0;border-radius:12px;background:#3d6fa5;color:#fff;cursor:pointer">📷 Scan bib tags</button>
    <div id="camwrap" style="display:none;position:relative;margin-bottom:.5rem">
      <video id="cv" playsinline muted style="width:100%;border-radius:12px;background:#000;display:block"></video>
      <canvas id="cc" style="position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none"></canvas>
    </div>
    <div id="cammsg" class="ph" style="min-height:1.1rem"></div>
    <input id="psearch" autocomplete="off" placeholder="search name…" oninput="renderElig()">
    <div id="plist" class="plist"></div>
  </div>
  <div id="banner" class="banner" style="display:none"></div>
  <div id="flist" class="flist" style="display:none">
    <div class="empty">Finishers appear here as you record them.</div>
  </div>
</div>
<div id="ctrls" class="ctrls" style="display:none">
  <button class="ctl undo" onclick="undo()">↶ UNDO</button>
  <button class="ctl stop" onclick="stopRace()">■ STOP</button>
</div>
<script>
const RID={rid};
let OFFSET=0, BEST_RTT=1e9, START=null, STOPMS=null, STOPPED=false, STARTED=false, MODE='tap', FIN=[];
function nowms(){{ return Date.now()+OFFSET; }}
function fmt(sec){{ if(sec==null)return''; sec=Math.max(0,sec);
  const h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec-3600*h-60*m;
  return h+':'+String(m).padStart(2,'0')+':'+s.toFixed(3).padStart(6,'0'); }}
let ELIG=[];
async function load(){{
  const t0=Date.now();
  const s=await jget('/races/'+RID+'/state');
  const t1=Date.now(), rtt=t1-t0;
  if(rtt<BEST_RTT){{ BEST_RTT=rtt; OFFSET=Math.round(s.server_ms+rtt/2-t1); }}  // keep the lowest-latency sample
  START=s.start_ms; STOPMS=s.stop_ms;
  STOPPED=s.stopped; STARTED=s.started; MODE=s.capture_mode; FIN=s.finishers;
  sync(); render();
  if((MODE==='tapselect'||MODE==='tap') && STARTED) loadElig();
}}
function sync(){{
  // Unified "tap -> scan or select": tap and tapselect both fill open slots by scan or pick.
  const active=STARTED&&!STOPPED, scan=MODE==='scan', sel=(MODE==='tapselect'||MODE==='tap');
  document.getElementById('startb').style.display = STARTED?'none':'';
  gunReflect(STARTED);
  if(!active && CAMON) stopScan();   // race ended / not running -> release the camera
  document.getElementById('tapb').style.display = (active&&!scan)?'':'none';
  document.getElementById('scanbox').style.display = (active&&scan)?'':'none';
  document.getElementById('pickbox').style.display = (STARTED&&sel)?'flex':'none';
  document.getElementById('flist').style.display = STARTED?'':'none';
  document.getElementById('ctrls').style.display = STARTED?'':'none';
  const b=document.getElementById('banner');
  if(STOPPED){{ b.style.display=''; b.textContent = scan ? '🏁 Race ended.'
    : (sel ? '🏁 Race ended — select who each open slot was.'
           : '🏁 Race ended — scan bibs on the console to fill open slots.'); }}
  else b.style.display='none';
  document.querySelector('.ctl.undo').disabled=!active;
  document.querySelector('.ctl.stop').disabled=!active;
}}
function openSlots(){{ return FIN.filter(f=>f.bib==null).sort((a,b)=>a.seq-b.seq); }}
async function loadElig(){{
  try{{ const d=await jget('/races/'+RID+'/eligible'); ELIG=d.runners||[]; }}catch(e){{ ELIG=[]; }}
  renderElig();
}}
function renderElig(){{
  const q=(document.getElementById('psearch').value||'').toLowerCase();
  const open=openSlots().length;
  document.getElementById('pickhint').textContent = open
    ? (open+' open slot'+(open>1?'s':'')+' — tap the runner who crossed')
    : 'Tap a finisher above, then select who it was';
  const rows=ELIG.filter(r=>!q||(r.name||'').toLowerCase().indexOf(q)>=0);
  const el=document.getElementById('plist');
  if(!rows.length){{ el.innerHTML='<div class="empty">'+(ELIG.length?'No match.':'Everyone is recorded. 🎉')+'</div>'; return; }}
  el.innerHTML=rows.map(r=>'<div class="pr" onclick="pick('+r.bib+')">'
    +'<span><span class="pnm">'+esc(r.name)+'</span>'
    +(r.meta?' <span class="pmeta">'+esc(r.meta)+'</span>':'')+'</span>'
    +'<span class="pbib">#'+r.bib+'</span></div>').join('');
}}
async function pick(bib){{
  const open=openSlots();
  if(!open.length){{ buzz([60,60,60]); alert('Tap the finisher first, then select who it was.'); return; }}
  try{{ await jpost('/finishers/'+open[0].id+'/bib',{{bib:bib}}); buzz(35); }}   // no popup on unregistered
  catch(e){{ alert(e.message); }}
  await load();
}}
// ---- inline bib-tag scanner: fills the next open (tapped) slot, alongside the picker ----
let CAMON=false, VS=null, DET=null, CCTX=null, DCAN=null, DCTX=null, CAMSEEN=new Set(), CAMRAF=null;
function toggleScan(){{ CAMON?stopScan():startScan(); }}
async function startScan(){{
  const msg=document.getElementById('cammsg');
  if(typeof AR==='undefined'){{ msg.textContent='Scanner not loaded — reload the page.'; return; }}
  try{{ VS=await navigator.mediaDevices.getUserMedia({{audio:false,video:{{facingMode:'environment',width:{{ideal:640}}}}}}); }}
  catch(e){{ msg.textContent='Camera unavailable — pick from the list instead.'; return; }}
  const v=document.getElementById('cv'); v.srcObject=VS; try{{ await v.play(); }}catch(e){{}}
  CAMON=true;
  document.getElementById('camwrap').style.display='';
  document.getElementById('scanToggle').textContent='📷 Stop scanning';
  DET=DET||new AR.Detector();
  CCTX=document.getElementById('cc').getContext('2d');
  DCAN=document.createElement('canvas'); DCTX=DCAN.getContext('2d',{{willReadFrequently:true}});
  scanLoop();
}}
function stopScan(){{ CAMON=false; if(CAMRAF)clearTimeout(CAMRAF);
  if(VS){{ VS.getTracks().forEach(function(t){{t.stop();}}); VS=null; }}
  const w=document.getElementById('camwrap'); if(w)w.style.display='none';
  const b=document.getElementById('scanToggle'); if(b)b.textContent='📷 Scan bib tags'; }}
function scanLoop(){{
  if(!CAMON)return;
  const v=document.getElementById('cv');
  if(v&&v.videoWidth){{
    const w=v.videoWidth,h=v.videoHeight;
    DCAN.width=w; DCAN.height=h; DCTX.drawImage(v,0,0,w,h);
    let ms=[]; try{{ ms=DET.detect(DCTX.getImageData(0,0,w,h)); }}catch(e){{}}
    const cc=document.getElementById('cc'); cc.width=w; cc.height=h; CCTX.clearRect(0,0,w,h);
    ms.forEach(function(m){{
      CCTX.strokeStyle='#28c76f'; CCTX.lineWidth=4; CCTX.beginPath();
      m.corners.forEach(function(p,i){{ i?CCTX.lineTo(p.x,p.y):CCTX.moveTo(p.x,p.y); }});
      CCTX.closePath(); CCTX.stroke();
      CCTX.fillStyle='#28c76f'; CCTX.font='bold 22px sans-serif'; CCTX.fillText('#'+m.id,m.corners[0].x,m.corners[0].y-8);
      camHit(m.id);
    }});
  }}
  CAMRAF=setTimeout(scanLoop,100);
}}
async function camHit(id){{
  if(!STARTED||CAMSEEN.has(id))return;
  CAMSEEN.add(id);
  const msg=document.getElementById('cammsg');
  try{{
    const j=await jpost('/races/'+RID+'/finish',{{bib:id,mode:'chute'}});
    if(j&&j.duplicate){{ msg.textContent='#'+id+' already recorded'; }}
    else{{ buzz(35); msg.innerHTML='📷 <b>#'+id+'</b>'+(j&&j.name?(' '+esc(j.name)):'')+' ✓'
      +(j&&j.warn?' <span style="color:var(--warn,#f0b429)">(not registered)</span>':'')
      +(j&&j.remaining!=null?(' · '+j.remaining+' open'):''); }}   // record + move on, no popup
    await load();
  }}catch(e){{ CAMSEEN.delete(id); msg.textContent='#'+id+' ✕ '+(e&&e.message?e.message:'error'); }}
}}
function tick(){{
  const c=document.getElementById('clock');
  if(!START){{ c.textContent='0:00:00.000'; return; }}
  const end=(STOPPED&&STOPMS)?STOPMS:nowms(); let e=(end-START)/1000; if(e<0)e=0;
  c.textContent=fmt(e);
}}
function render(){{
  document.getElementById('count').textContent=FIN.length;
  const list=document.getElementById('flist');
  if(!FIN.length){{ list.innerHTML='<div class="empty">Finishers appear here as you record them.</div>'; return; }}
  let h='';
  [...FIN].reverse().forEach(f=>{{
    const t=(f.elapsed_str||'');
    const who = f.name? esc(f.name) : (f.bib? ('Bib '+f.bib) : '—');
    h+='<div class="frow"><span class="fp">'+f.seq+'</span>'
      +'<span class="ft">'+t+'</span><span class="fw">'+who+'</span></div>';
  }});
  list.innerHTML=h;
}}
async function startRace(){{
  if(STARTED&&!STOPPED)return;   // already running (another phone/the gun started it) — don't re-post
  const body={{at:nowms()}};     // stamp the gun instant on THIS phone, immune to POST lag
  if(STOPPED&&FIN.length){{ if(!confirm('Race ended with '+FIN.length+' finisher(s). Restarting CLEARS them. Continue?'))return; body.clear=true; }}
  try{{ await jpost('/races/'+RID+'/start',body); }}catch(e){{ alert(e.message); }} load(); }}
async function stopRace(){{ if(!confirm('Stop the race clock?'))return; await jpost('/races/'+RID+'/stop',{{}}); load(); }}
function buzz(ms){{ try{{ navigator.vibrate && navigator.vibrate(ms); }}catch(e){{}} }}
async function tap(){{ buzz(35); const at=nowms(); try{{ await jpost('/races/'+RID+'/tap',{{at:at}}); }}catch(e){{}} load(); }}
async function undo(){{ buzz([20,40,20]); try{{ await jpost('/races/'+RID+'/untap',{{}}); }}catch(e){{ alert(e.message); }} load(); }}
async function rec(v){{ const el=document.getElementById('sbib'); v=(v||el.value).toString().trim(); if(!v)return;
  try{{ const j=await jpost('/races/'+RID+'/finish',{{bib:v}}); el.value='';
    if(!(j&&j.duplicate)) buzz(35); }}   // unregistered bibs record silently — no popup
  catch(e){{ buzz([60,60,60]); alert(e.message); }} load(); }}
// Screen wake lock: a timing phone that sleeps mid-race silently loses finishers.
let WL=null;
async function wlock(){{ try{{ WL=await navigator.wakeLock.request('screen'); }}catch(e){{}} }}
document.addEventListener('visibilitychange',()=>{{ if(document.visibilityState==='visible')wlock(); }});
wlock();
setInterval(tick,60);
setInterval(load,3000);
load();
{GUN_JS}
</script>
"""
    return _phone_doc(r["name"], body, TIMER_CSS)


# ------------------------------ track timer (two-tab) ------------------------------
@bp.get("/phone/meet/<int:mid>")
def phone_meet(mid):
    p = getattr(g, "principal", None)
    if not p:
        return redirect(f"/login?next=/phone/meet/{mid}")
    m = load_meet(mid)
    if not can_record_meet(m):
        abort(403)
    if m["sport"] in ("xc", "road"):  # XC heats / road events live on the pick page now
        return redirect("/phone")
    conn = db.connect()
    html = _track_timer(conn, m)
    conn.close()
    return shell(p, html, active="phone", bare=True)


def _track_timer(conn, m):
    """Two-tab Track Timer: Time race (event/heat pickers -> tap console) + Scan sheet."""
    tap_q = ",".join("?" * len(TAP_EVENTS))
    events = conn.execute(
        f"SELECT me.id, e.name AS ename, me.gender, me.grade FROM meet_events me "
        f"JOIN events e ON e.id=me.event_id WHERE me.meet_id=? AND e.name IN ({tap_q}) "
        f"ORDER BY (me.run_order IS NULL), me.run_order, e.sort, me.gender, me.grade",
        (m["id"], *TAP_EVENTS)).fetchall()
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
    # Laned sprints/relays -> lane-timing (one volunteer per lane).
    lane_q = ",".join("?" * len(LANE_EVENTS))
    lane_events = conn.execute(
        f"SELECT me.id, e.name AS ename, me.gender, me.grade FROM meet_events me "
        f"JOIN events e ON e.id=me.event_id WHERE me.meet_id=? AND e.name IN ({lane_q}) "
        f"ORDER BY (me.run_order IS NULL), me.run_order, e.sort, me.gender, me.grade",
        (m["id"], *LANE_EVENTS)).fetchall()
    lanedata, lane_opts = {}, ['<option value="">— pick sprint / relay —</option>']
    for ev in lane_events:
        heats = [r[0] for r in conn.execute(
            "SELECT DISTINCT heat FROM entries WHERE meet_event_id=? AND heat IS NOT NULL "
            "ORDER BY heat", (ev["id"],)).fetchall()]
        gword = {"M": "Boys", "F": "Girls"}.get(ev["gender"], "")
        gr = f"{ev['grade']}th Grade " if ev["grade"] else ""
        label = f"{gr}{gword + ' ' if gword else ''}{ev['ename']}".strip()
        lanedata[str(ev["id"])] = {"label": label, "heats": heats}
        lane_opts.append(f'<option value="{ev["id"]}">{escape(label)}</option>')
    # Meet switcher (track meets the user can time) — hidden for a no-login QR
    # session, which is already locked to this one meet.
    scoped = bool(getattr(getattr(g, "principal", None), "meet_scope", None))
    meet_opts = []
    if not scoped:
        for mm in conn.execute("SELECT * FROM meets WHERE district_id=? AND sport='track' "
                               "ORDER BY date DESC, id DESC", (m["district_id"],)).fetchall():
            if can_record_meet(mm):
                sel = "selected" if mm["id"] == m["id"] else ""
                meet_opts.append(f'<option value="{mm["id"]}" {sel}>{escape(mm["name"])}</option>')
    meet_block = ("" if scoped else
                  '<label>Meet</label>'
                  "<select onchange=\"if(this.value)location.href='/phone/meet/'+this.value\">"
                  f'{"".join(meet_opts)}</select>')

    # Open-pit field events. Long Jump / Shot Put take three attempts; High Jump takes only
    # the best height cleared here (bar-by-bar make/miss stays on the paper heat sheet).
    field_evs = conn.execute(
        "SELECT DISTINCT e.id, e.name FROM events e JOIN meet_events me ON me.event_id=e.id "
        "WHERE me.meet_id=? AND e.kind='field' ORDER BY e.sort",
        (m["id"],)).fetchall()
    field_opts = ("".join(
        f'<option value="{e["id"]}" data-hj="{1 if e["name"] == "High Jump" else 0}">'
        f'{escape(e["name"])}</option>' for e in field_evs)
        or '<option value="">— no field events at this meet —</option>')

    return f"""
<h1>🏅 Track Timer</h1>
<div class="seg">
  <button id="seg-time" onclick="segTab('time')">⏱ Time</button>
  <button id="seg-scan" class="ghost" onclick="segTab('scan')">📷 Scan</button>
  <button id="seg-pit" class="ghost" onclick="segTab('pit')">🏖 Pit</button>
</div>

<div class="card" id="tab-time">
  <h2>Time a race</h2>
  <p class="sub">For 800m, 1600m, 3200m &amp; 4×400m — start the clock and tap each runner as they finish.</p>
  {meet_block}
  <label>Event</label>
  <select id="tev" onchange="fillHeats()">{''.join(ev_opts)}</select>
  <label>Heat / section</label>
  <select id="tht" onchange="upd()"></select>
  <button id="startbtn" onclick="startRace()" disabled style="width:100%;margin-top:1rem;padding:.8rem">Open race timer →</button>
  <hr style="border:0;border-top:1px solid var(--line);margin:1.2rem 0">
  <h2 style="margin:.2rem 0">🏁 Sprints &amp; relays</h2>
  <p class="sub">100m / 200m / 400m / 4×100m run in lanes — one volunteer per lane, each taps when their lane crosses.</p>
  <label>Event</label>
  <select id="laneev" onchange="fillLaneHeats()">{''.join(lane_opts)}</select>
  <label>Heat / section</label>
  <select id="laneht" onchange="laneUpd()"></select>
  <button id="lanebtn" onclick="openLane()" disabled style="width:100%;margin-top:1rem;padding:.8rem">Open lane timer →</button>
</div>

<div class="card" id="tab-scan" style="display:none">
  <h2>Scan a heat sheet</h2>
  <p class="sub">Take a photo of a marked-up heat sheet — the event is read from the
  sheet's code, and the results are posted to it.</p>
  <label>Photo of the sheet</label>
  <input type="file" id="scanf" accept="image/*" capture="environment" onchange="doScan()">
  <p class="muted">Keep the code/QR in the top-right corner of the sheet in frame.</p>
  <div id="scanout"></div>
</div>

<div class="card" id="tab-pit" style="display:none">
  <h2>🏖 Open pit</h2>
  <p class="sub">Record whoever steps up, by bib — the mark files into that athlete's own
  division automatically. Enter feet-inches — just type <b>10 6</b> for 10&#39;6&quot; (a dash or
  apostrophe works too). <b>F</b> = foul.</p>
  <label>Event</label>
  <select id="pev" onchange="pitMode()">{field_opts}</select>
  <label>Enter bib #</label>
  <input id="pbib" inputmode="numeric" autocomplete="off" placeholder="enter bib #"
    oninput="pitLookup()"
    onkeydown="if(event.key==='Enter')document.getElementById(pitIsHJ()?'pahj':'pa0').focus()"
    style="font-size:1.3rem;padding:.7rem">
  <div id="pbibinfo" style="min-height:1.3rem;margin-top:.3rem;font-size:1rem"></div>
  <div id="attsblock">
    <label>Attempts</label>
    <div class="pitatts">
      <input id="pa0" inputmode="text">
      <input id="pa1" inputmode="text">
      <input id="pa2" inputmode="text" onkeydown="if(event.key==='Enter')pitPost()">
    </div>
  </div>
  <div id="hjblock" style="display:none">
    <label>Best height cleared</label>
    <input id="pahj" inputmode="text" placeholder="e.g. 4 10 for 4&#39;10&quot;"
      onkeydown="if(event.key==='Enter')pitPost()" style="font-size:1.3rem;padding:.7rem">
    <p class="muted" style="margin:.4rem 0 0">High Jump records the <b>best height cleared</b> only.
    Keep the bar-by-bar make/miss on your paper heat sheet.</p>
  </div>
  <button onclick="pitPost()" style="width:100%;margin-top:1rem;padding:1rem;font-size:1.15rem">✔ Record mark</button>
  <div id="pmsg" style="margin-top:.6rem"></div>
  <table id="plog" style="margin-top:.8rem"></table>
</div>

<style>
.seg{{display:flex;gap:.4rem;margin:.4rem 0 1rem}}
.seg button{{flex:1;padding:.85rem .3rem;font-size:1rem}}
.pitatts{{display:flex;gap:.5rem}}
.pitatts input{{text-align:center;font-size:1.2rem;padding:.6rem}}
#plog td{{padding:.4rem .3rem;border-top:1px solid var(--line)}}
</style>
<script>
const EV={json.dumps(evdata)};
const LANEV={json.dumps(lanedata)};
let SCAN_MEID=null;
function segTab(t){{
  ['time','scan','pit'].forEach(function(k){{
    document.getElementById('tab-'+k).style.display = (k===t)?'':'none';
    document.getElementById('seg-'+k).className = (k===t)?'':'ghost';
  }});
}}
function pitIsHJ(){{var o=document.getElementById('pev').selectedOptions[0];return !!(o&&o.dataset.hj==='1');}}
function pitMode(){{var hj=pitIsHJ();
  document.getElementById('attsblock').style.display=hj?'none':'';
  document.getElementById('hjblock').style.display=hj?'':'none';
  pitLookup();}}
let _pitLT=null;
function pitLookup(){{
  clearTimeout(_pitLT);
  const bib=document.getElementById('pbib').value.trim();
  const info=document.getElementById('pbibinfo');
  if(!bib){{ info.textContent=''; return; }}
  info.innerHTML='<span class="muted">…</span>';
  _pitLT=setTimeout(async function(){{
    try{{
      const ev=document.getElementById('pev').value;
      const j=await jget('/meets/{m['id']}/pit/lookup?bib='+encodeURIComponent(bib)+'&event='+encodeURIComponent(ev));
      if(document.getElementById('pbib').value.trim()!==bib) return;   // stale
      if(!j.found){{
        info.innerHTML='<span style="color:var(--warn)">no athlete with bib '+esc(bib)+' at this meet</span>';
        return;
      }}
      let s='<b style="color:var(--ok)">✔ '+esc(j.name)+'</b>'
        +'<span class="muted"> · '+esc(j.school)+' · '+esc(j.division)+'</span>';
      // Load any already-recorded attempts straight into the boxes so they can be
      // reviewed/edited (re-recording replaces them). Blank boxes = nothing on file.
      const att=j.attempts||[];
      if(pitIsHJ()){{ document.getElementById('pahj').value = att[0] || ''; }}
      else {{ for(let k=0;k<3;k++){{ document.getElementById('pa'+k).value = att[k] || ''; }} }}
      if(att.some(function(x){{return x;}})){{
        s+='<span class="muted"> · marks on file loaded below — edit &amp; record to update</span>';
      }}
      info.innerHTML=s;
    }}catch(e){{ info.textContent=''; }}
  }}, 250);
}}
async function pitPost(){{
  const ev=document.getElementById('pev').value, bib=document.getElementById('pbib').value.trim();
  const hj=pitIsHJ();
  const atts = hj ? [document.getElementById('pahj').value.trim()]
                  : [0,1,2].map(function(k){{return document.getElementById('pa'+k).value.trim();}});
  const box=document.getElementById('pmsg');
  if(!ev){{box.innerHTML='<p class="msg err">No field events at this meet.</p>';return;}}
  if(!bib){{box.innerHTML='<p class="msg err">Enter a bib.</p>';return;}}
  if(!atts.some(function(a){{return a;}})){{box.innerHTML='<p class="msg err">'+(hj?'Enter the best height cleared.':'Enter at least one attempt.')+'</p>';return;}}
  try{{
    const j=await jpost('/meets/{m['id']}/pit/post',{{event_id:ev,bib:bib,attempts:atts}});
    box.innerHTML='<p class="msg ok">✔ '+esc(j.name)+' · <b>'+esc(j.event)+'</b> · '+esc(j.division)+' · best '+esc(j.best||'—')+'</p>';
    document.getElementById('plog').insertAdjacentHTML('afterbegin',
      '<tr><td><b>#'+esc(bib)+'</b></td><td>'+esc(j.name)+'</td>'
      +'<td class="muted">'+esc(j.event)+'</td>'
      +'<td><b>'+esc(j.best||'')+'</b></td></tr>');
    ['pbib','pa0','pa1','pa2','pahj'].forEach(function(k){{document.getElementById(k).value='';}});
    document.getElementById('pbibinfo').textContent='';
    document.getElementById('pbib').focus();
  }}catch(e){{ box.innerHTML='<p class="msg err">'+esc(e.message)+'</p>'; }}
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
function fillLaneHeats(){{
  const ev=document.getElementById('laneev').value, ht=document.getElementById('laneht');
  ht.innerHTML='';
  const d=LANEV[ev];
  if(!d){{ht.innerHTML='<option value="">— pick an event first —</option>';laneUpd();return;}}
  if(!d.heats.length){{ht.innerHTML='<option value="">no heats — draw them first</option>';laneUpd();return;}}
  d.heats.forEach(function(h){{ht.innerHTML+='<option value="'+h+'">Heat '+h+'</option>';}});
  laneUpd();
}}
function laneUpd(){{
  const ev=document.getElementById('laneev').value, ht=document.getElementById('laneht').value;
  document.getElementById('lanebtn').disabled = !(ev && ht);
}}
function openLane(){{
  const ev=document.getElementById('laneev').value, ht=document.getElementById('laneht').value;
  if(ev&&ht) location.href='/meet-events/'+ev+'/lanes?heat='+ht;
}}
async function doScan(){{
  const f=document.getElementById('scanf').files[0];
  if(!f)return;
  document.getElementById('scanout').innerHTML='<p class="muted">Reading the sheet…</p>';
  const fd=new FormData(); fd.append('image',f);
  const r=await fetch('/track/scan',{{method:'POST',body:fd}});
  const j=await r.json();
  if(!r.ok){{document.getElementById('scanout').innerHTML='<p class="msg err">'+esc(j.error||'Could not read the sheet')+'</p>';return;}}
  SCAN_MEID=j.meid; window.SCAN_FIELD=!!j.field; window.SCAN_HJ=!!j.hj;
  if(!(j.marks||[]).length){{document.getElementById('scanout').innerHTML='<p class="msg err">Read <b>'+esc(j.label)+'</b> but found no marks — retake the photo.</p>';return;}}
  let h='<p><b>Detected:</b> '+esc(j.label)+'</p><p class="muted">Review, then post. Unknown bibs at this meet are entered automatically.</p><table>';
  const dqtd=i=>'<td><input type="checkbox" id="sd'+i+'" style="width:auto"></td>';
  if(SCAN_HJ){{
    h+='<tr><th>Bib</th><th>Best height</th><th>Misses</th><th>DQ</th></tr>';
    j.marks.forEach(function(m,i){{h+='<tr><td><input id="sb'+i+'" value="'+esc(m.bib==null?'':m.bib)+'" style="width:56px"></td>'
      +'<td><input id="sh'+i+'" value="'+esc(m.height==null?'':m.height)+'" placeholder="4-08" style="width:80px"></td>'
      +'<td><input id="sx'+i+'" value="'+esc(m.misses==null?'':m.misses)+'" style="width:50px"></td>'+dqtd(i)+'</tr>';}});
  }} else if(SCAN_FIELD){{
    h+='<tr><th>Bib</th><th>A1</th><th>A2</th><th>A3</th><th>DQ</th></tr>';
    j.marks.forEach(function(m,i){{ var a=m.attempts||['','',''];
      h+='<tr><td><input id="sb'+i+'" value="'+esc(m.bib==null?'':m.bib)+'" style="width:56px"></td>'
        +[0,1,2].map(function(k){{return '<td><input id="sa'+i+'_'+k+'" value="'+esc(a[k]||'')+'" style="width:62px"></td>';}}).join('')+dqtd(i)+'</tr>';}});
  }} else {{
    h+='<tr><th>Bib</th><th>Mark</th><th>DQ</th></tr>';
    j.marks.forEach(function(m,i){{h+='<tr><td><input id="sb'+i+'" value="'+esc(m.bib==null?'':m.bib)+'" style="width:70px"></td>'
      +'<td><input id="sm'+i+'" value="'+esc(m.mark==null?'':m.mark)+'" style="width:120px"></td>'+dqtd(i)+'</tr>';}});
  }}
  h+='</table><button onclick="postScan('+j.marks.length+')" style="margin-top:.6rem">Post to '+esc(j.label)+'</button>';
  document.getElementById('scanout').innerHTML=h;
}}
async function postScan(n){{
  if(!SCAN_MEID)return;
  const marks=[];
  const dqv=i=>{{const el=document.getElementById('sd'+i);return !!(el&&el.checked);}};
  for(let i=0;i<n;i++){{const b=document.getElementById('sb'+i).value.trim();if(!b)continue;
    if(window.SCAN_HJ){{var ht=document.getElementById('sh'+i).value.trim();var mi=document.getElementById('sx'+i).value.trim();
      if(ht)marks.push({{bib:b,height:ht,misses:mi?parseInt(mi):null,dq:dqv(i)}});}}
    else if(window.SCAN_FIELD){{var a=[0,1,2].map(function(k){{return document.getElementById('sa'+i+'_'+k).value.trim();}});
      if(a.some(function(x){{return x;}})) marks.push({{bib:b,attempts:a,dq:dqv(i)}});}}
    else {{const mk=document.getElementById('sm'+i).value.trim();if(mk)marks.push({{bib:b,mark:mk,dq:dqv(i)}});}}
  }}
  try{{const j=await jpost('/meet-events/'+SCAN_MEID+'/scan/post',{{marks}});
    let msg='Posted '+j.applied+' marks';
    if(j.added&&j.added.length)msg+='; added last-minute: '+j.added.join(', ');
    if(j.unmatched&&j.unmatched.length)msg+='; unknown bibs: '+j.unmatched.join(', ');
    alert(msg);location.reload();}}
  catch(e){{alert(e.message);}}
}}
pitMode();
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
