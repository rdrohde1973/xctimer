"""Cross-country timing engine (handoff §8). Reference: ~/xc-district/xc_district.py.

Races + finishers, a tap-to-finish timing console, bib assignment with results
snapshotting, DQ, reorder (times stay in slots), combined results across races by
gender, MileSplit-style team scoring, xlsx export, and a public results page.
"""
import io
from collections import defaultdict
from datetime import datetime, timezone

from markupsafe import escape
from flask import Blueprint, request, redirect, g, abort, jsonify, Response

from . import db, demo
from .auth import login_required
from .tenancy import active_district_id, all_districts
from .ui import shell, BRAND_HTML, CSS, HEAD_EXTRA
from .meets import (load_meet, can_view_meet, can_setup_meet, can_record_meet)

bp = Blueprint("xc", __name__)


# ------------------------------- helpers -------------------------------
def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat()


def _parse(s):
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def fmt_time(sec):
    if sec is None:
        return ""
    m = int(sec // 60)
    s = sec - 60 * m
    return f"{m}:{s:04.1f}"


def fmt_hms(sec):
    """Console/finisher clock: H:MM:SS.mmm (matches the old app's timer)."""
    if sec is None:
        return ""
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - 3600 * h - 60 * m
    return f"{h}:{m:02d}:{s:06.3f}"


def _race_or_403(rid, check):
    conn = db.connect()
    r = conn.execute("SELECT * FROM races WHERE id=?", (rid,)).fetchone()
    conn.close()
    if not r:
        abort(404)
    m = load_meet(r["meet_id"])
    if not check(m):
        abort(403)
    return r, m


def _athlete_for_bib(conn, meet_id, bib):
    return conn.execute(
        "SELECT a.name, a.grade, a.gender, s.name AS sname FROM athletes a "
        "JOIN schools s ON s.id=a.school_id "
        "JOIN meet_schools ms ON ms.school_id=a.school_id "
        "WHERE ms.meet_id=? AND a.bib=? LIMIT 1", (meet_id, bib)).fetchone()


CAPTURE_MODES = [("tap", "Tap then scan"), ("scan", "Scan at finish")]


def setup_section(m, setup):
    """Heats card for the meet setup page (team-scoring toggle + heat table)."""
    import json as _json
    conn = db.connect()
    races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (m["id"],)).fetchall()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT r.id, COUNT(f.id) FROM races r LEFT JOIN finishers f ON f.race_id=r.id "
        "WHERE r.meet_id=? GROUP BY r.id", (m["id"],)).fetchall()}
    conn.close()

    ts_toggle = ""
    if setup:
        chk = "checked" if m["team_scoring"] else ""
        ts_toggle = (
            f'<form method="post" action="/meets/{m["id"]}/scoring" style="margin-bottom:.6rem">'
            f'<label style="display:flex;gap:.5rem;align-items:center">'
            f'<input type="checkbox" name="team_scoring" style="width:auto" {chk} onchange="this.form.submit()"> '
            f'<b>Team scoring</b> <span class="muted">— adds team scores (top 5 per school) to results</span></label></form>')

    rows = []
    for r in races:
        status = "ended" if r["stop_time"] else ("running" if r["start_time"] else "not started")
        act = f'<a class="btn" href="/races/{r["id"]}/console">⏱ Time</a>'
        if setup:
            nm = _json.dumps(r["name"])
            act += (
                f" <button class='ghost' onclick='renameHeat({r['id']}, {escape(nm)})'>✎</button>"
                f" <form class='inline' method='post' action='/races/{r['id']}/delete' "
                f"onsubmit=\"return confirm('Delete heat?')\"><button class='danger'>✕</button></form>")
        rows.append(
            f'<tr><td><b>{escape(r["name"])}</b></td><td>{r["capture_mode"]}</td>'
            f'<td>{status}</td><td>{counts.get(r["id"], 0)}</td>'
            f'<td style="text-align:right">{act}</td></tr>')
    tbl = (f'<table><tr><th>Heat</th><th>Mode</th><th>Status</th><th>Finishers</th><th></th></tr>'
           f'{"".join(rows)}</table>' if races else '<p class="muted">No heats yet.</p>')

    add = ""
    if setup:
        opts = "".join(f'<option value="{v}">{escape(lbl)}</option>' for v, lbl in CAPTURE_MODES)
        add = (
            f'<form method="post" action="/meets/{m["id"]}/races" class="row" style="margin-top:.8rem">'
            f'<div><input name="name" placeholder="Heat name (e.g. Girls)"></div>'
            f'<div style="max-width:200px"><select name="capture_mode">{opts}</select></div>'
            f'<div style="display:flex;align-items:flex-end"><button type="submit">+ Add heat</button></div>'
            f'</form>'
            f'<script>function renameHeat(id,cur){{var n=prompt("Heat name",cur);if(!n)return;'
            f'var f=document.createElement("form");f.method="post";f.action="/races/"+id+"/rename";'
            f'var i=document.createElement("input");i.name="name";i.value=n;f.appendChild(i);'
            f'document.body.appendChild(f);f.submit();}}</script>')
    return f'<div class="card"><h2>Heats</h2>{ts_toggle}{tbl}{add}</div>'


# ------------------------------- races -------------------------------
@bp.post("/meets/<int:mid>/races")
@login_required
def create_race(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    name = (request.form.get("name") or "").strip() or "Heat"
    mode = request.form.get("capture_mode")
    mode = mode if mode in ("tap", "scan") else "tap"
    conn = db.connect()
    conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)",
                 (mid, name, mode))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


@bp.post("/races/<int:rid>/rename")
@login_required
def rename_race(rid):
    r, m = _race_or_403(rid, can_setup_meet)
    name = (request.form.get("name") or "").strip()
    mode = request.form.get("capture_mode")
    conn = db.connect()
    if name:
        conn.execute("UPDATE races SET name=? WHERE id=?", (name, rid))
    if mode in ("tap", "scan"):
        conn.execute("UPDATE races SET capture_mode=? WHERE id=?", (mode, rid))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{m['id']}")


@bp.post("/races/<int:rid>/delete")
@login_required
def delete_race(rid):
    r, m = _race_or_403(rid, can_setup_meet)
    conn = db.connect()
    conn.execute("DELETE FROM finishers WHERE race_id=?", (rid,))
    conn.execute("DELETE FROM races WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{m['id']}")


# ------------------------------- meet-day tabs -------------------------------
def _xc_tabs(mid, active):
    """Tab bar for XC meets (parallels track's). XC has no per-event assignment,
    so: Setup (config) · Meet day (run the heats + print) · Results."""
    def tab(href, label, key):
        on = "background:var(--panel2);color:var(--fg)" if active == key else "color:var(--mut)"
        return (f'<a href="{href}" style="padding:.4rem .9rem;border-radius:8px;'
                f'text-decoration:none;{on}">{label}</a>')
    return ('<div style="display:flex;gap:.3rem;margin:.4rem 0 1rem;border-bottom:1px solid var(--line);'
            'padding-bottom:.5rem;flex-wrap:wrap">'
            + tab(f"/meets/{mid}", "⚙️ Setup", "setup")
            + tab(f"/meets/{mid}/xc-day", "🏁 Meet day", "meetday")
            + tab(f"/meets/{mid}/results", "📊 Results", "results")
            + '</div>')


@bp.get("/meets/<int:mid>/xc-day")
@login_required
def xc_meet_day(mid):
    """Day-of view: run each heat's timing console + print stickers / bib lists."""
    m = load_meet(mid)
    if not can_view_meet(m) or m["sport"] != "xc":
        abort(403)
    conn = db.connect()
    races = conn.execute("SELECT * FROM races WHERE meet_id=? ORDER BY id", (mid,)).fetchall()
    counts = {r[0]: r[1] for r in conn.execute(
        "SELECT r.id, COUNT(f.id) FROM races r LEFT JOIN finishers f ON f.race_id=r.id "
        "WHERE r.meet_id=? GROUP BY r.id", (mid,)).fetchall()}
    conn.close()
    rows = []
    for r in races:
        status = "ended" if r["stop_time"] else ("running" if r["start_time"] else "not started")
        rows.append(
            f'<tr><td><b>{escape(r["name"])}</b></td><td>{r["capture_mode"]}</td>'
            f'<td>{status}</td><td>{counts.get(r["id"], 0)}</td>'
            f'<td style="text-align:right"><a class="btn" href="/races/{r["id"]}/console">⏱ Time</a></td></tr>')
    tbl = (f'<div class="card"><h2>Heats — tap to time</h2><table><tr><th>Heat</th><th>Mode</th>'
           f'<th>Status</th><th>Finishers</th><th></th></tr>{"".join(rows)}</table></div>'
           if races else '<div class="card muted">No heats yet — add them on the Setup tab.</div>')
    print_bar = (
        f'<div class="card"><b>Print:</b> '
        f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5160">Stickers 5160</a> '
        f'<a class="btn ghost" href="/meets/{mid}/stickers.pdf?template=5163">Stickers 5163</a> '
        f'<a class="btn ghost" href="/meets/{mid}/biblist.pdf">Bib lists</a></div>')
    body = (f'<p class="muted"><a href="/meets">← Meets</a></p><h1>{escape(m["name"])}</h1>'
            f'{_xc_tabs(mid, "meetday")}{tbl}{print_bar}')
    return shell(g.principal, body, active="meets")


# ------------------------------- timing console -------------------------------
CONSOLE_CSS = """
.tc-clock{font-size:3.2rem;font-weight:800;font-variant-numeric:tabular-nums;
  text-align:center;letter-spacing:-.02em;line-height:1}
.tc-clock.stopped{color:var(--err)}
.tc-btns{display:flex;gap:.6rem;justify-content:center;align-items:center;flex-wrap:wrap;margin:1rem 0 .2rem}
.tc-btns button,.tc-btns .btn{font-size:1.05rem;padding:.7rem 1.3rem}
.tc-btns #btn-start{background:var(--ok);color:#04101f;font-size:1.4rem;padding:1rem 2.6rem}
.tc-btns #btn-start:hover{background:#34a86e}
.tc-btns #btn-start:disabled{opacity:.4;cursor:default}
.tc-btns #btn-stop{background:var(--err);color:#fff}
.tc-btns #btn-stop:hover{background:#d9534f}
.tc-btns #btn-stop:disabled{opacity:.4;cursor:default}
.tc-status{text-align:center;font-weight:600;padding:.5rem;border-radius:8px;margin-top:.5rem}
.tc-status.wait{color:var(--warn)}
.tc-status.run{color:var(--ok)}
.tc-status.end{color:var(--err);background:rgba(240,98,91,.12)}
.tc-bibrow{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap}
.tc-bibrow input{max-width:170px;font-size:1.1rem}
.tc-bibrow #slot{margin-left:.2rem}
#rows td{vertical-align:middle}
#rows .grip{cursor:grab;color:var(--dim);text-align:center;font-size:1.1rem;width:1.4rem}
#rows tr.drag-over td{border-top:2px solid var(--acc)}
"""


@bp.get("/races/<int:rid>/console")
@login_required
def console(rid):
    r, m = _race_or_403(rid, can_record_meet)
    body = f"""
<style>{CONSOLE_CSS}</style>
<p class="muted"><a href="/meets/{m['id']}">← {escape(m['name'])}</a></p>
<h1>{escape(r['name'])} <span class="muted" style="font-weight:400">· {escape(m['name'])}</span></h1>
<div class="card">
  <div id="clock" class="tc-clock">0:00:00.000</div>
  <div class="tc-btns">
    <button id="btn-start" onclick="startRace()">🚦 Start</button>
    <button id="btn-stop" onclick="stopRace()">⏹ Stop</button>
    <button class="ghost" onclick="resetRace()">🔄 Reset</button>
    <a class="btn ghost" href="/meets/{m['id']}/results">📊 Results</a>
  </div>
  <div id="status" class="tc-status wait">Not started.</div>
</div>
<div class="card">
  <div class="tc-bibrow">
    <strong>Bib #</strong>
    <input id="bib" placeholder="scan/type" autocomplete="off" autocapitalize="off"
      onkeydown="if(event.key==='Enter')recordBib()">
    <button onclick="recordBib()">✔ <span id="verb">Assign</span></button>
    <span id="slot" class="muted"></span>
  </div>
  <div id="help" class="muted" style="margin-top:.5rem"></div>
</div>
<div class="card"><h2>Finishers (<span id="count">0</span>)</h2>
  <table><thead><tr><th></th><th>#</th><th>Bib</th><th>Name</th><th>School</th><th>Time</th><th></th></tr></thead>
  <tbody id="rows"></tbody></table>
</div>
<script>
const RID={rid}, MID={m['id']};
let OFFSET=0, START=null, STOPMS=null, STOPPED=false, STARTED=false, MODE='tap', FIN=[], OPEN=0;
let dragId=null, dragging=false;
function nowms(){{ return Date.now()+OFFSET; }}
function fmt(sec){{ if(sec==null)return''; sec=Math.max(0,sec);
  const h=Math.floor(sec/3600), m=Math.floor((sec%3600)/60), s=sec-3600*h-60*m;
  return h+':'+String(m).padStart(2,'0')+':'+s.toFixed(3).padStart(6,'0'); }}
async function load(){{
  const s=await jget('/races/'+RID+'/state');
  OFFSET=s.server_ms-Date.now(); START=s.start_ms; STOPMS=s.stop_ms;
  STOPPED=s.stopped; STARTED=s.started; MODE=s.capture_mode; FIN=s.finishers; OPEN=s.open;
  syncUI(); render();
}}
function syncUI(){{
  const scan = MODE==='scan';
  document.getElementById('btn-start').disabled = STARTED && !STOPPED;
  document.getElementById('btn-stop').disabled = !STARTED || STOPPED;
  document.getElementById('verb').textContent = scan?'Record':'Assign';
  document.getElementById('help').textContent = scan
    ? 'Scan mode: each bib records with the current race time.'
    : 'Tap mode: taps come from the phone; scan bibs here to fill open slots in order.';
  const st=document.getElementById('status');
  if(!STARTED){{ st.className='tc-status wait'; st.textContent='Not started.'; }}
  else if(STOPPED){{ st.className='tc-status end';
    st.textContent = scan?'🏁 Race ended.':'🏁 Race ended — keep scanning bibs to fill open slots.'; }}
  else {{ st.className='tc-status run'; st.textContent='🟢 Running.'; }}
  const slot=document.getElementById('slot');
  if(scan){{ slot.textContent=''; }}
  else {{ const nx=FIN.find(f=>f.bib==null);
    slot.textContent = OPEN? (OPEN+' open — next #'+nx.seq+' @ '+fmt(nx.elapsed)) : 'no open slots'; }}
}}
function tick(){{
  const c=document.getElementById('clock');
  if(!START){{ c.textContent='0:00:00.000'; c.classList.remove('stopped'); return; }}
  const end=(STOPPED&&STOPMS)?STOPMS:nowms(); let e=(end-START)/1000; if(e<0)e=0;
  c.textContent=fmt(e); c.classList.toggle('stopped',STOPPED);
}}
function render(){{
  document.getElementById('count').textContent=FIN.length;
  if(!FIN.length){{ document.getElementById('rows').innerHTML=
    '<tr><td colspan=7 class="muted">No finishers yet.</td></tr>'; return; }}
  let h='';
  FIN.forEach(f=>{{
    const nm = f.name? esc(f.name) : (f.bib?'':'<span class=muted>—</span>');
    const name = f.dq? ('<s>'+nm+' (DQ)</s>') : nm;
    h+='<tr draggable="true" data-id="'+f.id+'" ondragstart="dstart(event,'+f.id+')"'
     +' ondragover="dover(event,this)" ondragleave="this.classList.remove(\\'drag-over\\')"'
     +' ondrop="ddrop(event,'+f.id+')" ondragend="dend()">'
     +'<td class="grip">⠿</td><td>'+f.seq+'</td>'
     +'<td><input value="'+(f.bib??'')+'" style="width:64px" onchange="setBib('+f.id+',this.value)"></td>'
     +'<td>'+name+'</td><td>'+esc(f.school||'')+'</td>'
     +'<td style="font-variant-numeric:tabular-nums">'+fmt(f.elapsed)+'</td>'
     +'<td style="text-align:right;white-space:nowrap">'
     +'<button class="ghost" onclick="dq('+f.id+')">'+(f.dq?'un-DQ':'DQ')+'</button> '
     +'<button class="danger" onclick="del('+f.id+')">✕</button></td></tr>';
  }});
  document.getElementById('rows').innerHTML=h;
}}
async function startRace(){{ await jpost('/races/'+RID+'/start',{{}}); load(); }}
async function stopRace(){{ await jpost('/races/'+RID+'/stop',{{}}); load(); }}
async function resetRace(){{ if(!confirm('Reset clears the clock and all finishers. Continue?'))return;
  await jpost('/races/'+RID+'/reset',{{}}); load(); }}
async function recordBib(){{ const el=document.getElementById('bib'); const v=el.value.trim(); if(!v)return;
  try{{ await jpost('/races/'+RID+'/finish',{{bib:v}}); el.value=''; el.focus(); load(); }}
  catch(e){{ alert(e.message); el.select(); }} }}
async function setBib(id,v){{ try{{ await jpost('/finishers/'+id+'/bib',{{bib:v}}); }}catch(e){{ alert(e.message); }} load(); }}
async function dq(id){{ await jpost('/finishers/'+id+'/dq',{{}}); load(); }}
async function del(id){{ if(!confirm('Delete finisher?'))return; await jpost('/finishers/'+id+'/delete',{{}}); load(); }}
function dstart(e,id){{ dragging=true; dragId=id; e.dataTransfer.effectAllowed='move'; }}
function dover(e,tr){{ e.preventDefault(); tr.classList.add('drag-over'); }}
async function ddrop(e,overId){{ e.preventDefault();
  document.querySelectorAll('#rows tr').forEach(t=>t.classList.remove('drag-over'));
  if(dragId==null||dragId===overId){{ dend(); return; }}
  const order=FIN.map(f=>f.id); const from=order.indexOf(dragId), to=order.indexOf(overId);
  order.splice(to,0,order.splice(from,1)[0]);
  dend(); await jpost('/races/'+RID+'/reorder',{{order}}); load(); }}
function dend(){{ dragging=false; dragId=null; }}
setInterval(tick,75);
setInterval(()=>{{ if(!dragging)load(); }},2000);
load();
</script>
"""
    return shell(g.principal, body, active="meets")


@bp.get("/races/<int:rid>/state")
@login_required
def race_state(rid):
    r, m = _race_or_403(rid, can_record_meet)
    conn = db.connect()
    rows = conn.execute("SELECT * FROM finishers WHERE race_id=? ORDER BY seq", (rid,)).fetchall()
    conn.close()
    start = _parse(r["start_time"])
    stop = _parse(r["stop_time"])
    fins = [{
        "id": f["id"], "seq": f["seq"], "bib": f["bib"],
        "elapsed": f["elapsed_seconds"], "elapsed_str": fmt_hms(f["elapsed_seconds"]),
        "dq": bool(f["dq"]),
        "name": f["snap_name"], "school": f["snap_school"],
    } for f in rows]
    return jsonify(
        name=r["name"],
        capture_mode=r["capture_mode"],
        start_ms=_ms(start) if start else None,
        stop_ms=_ms(stop) if stop else None,
        started=bool(r["start_time"]),
        stopped=bool(r["stop_time"]),
        open=sum(1 for f in rows if f["bib"] is None),
        server_ms=_ms(_now()),
        finishers=fins,
    )


@bp.post("/races/<int:rid>/start")
@login_required
def race_start(rid):
    r, m = _race_or_403(rid, can_record_meet)
    conn = db.connect()
    conn.execute("UPDATE races SET start_time=?, stop_time=NULL WHERE id=?", (_iso(_now()), rid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/races/<int:rid>/stop")
@login_required
def race_stop(rid):
    r, m = _race_or_403(rid, can_record_meet)
    conn = db.connect()
    conn.execute("UPDATE races SET stop_time=? WHERE id=?", (_iso(_now()), rid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/races/<int:rid>/reset")
@login_required
def race_reset(rid):
    """Clear the clock and every finisher — a clean slate for the heat."""
    r, m = _race_or_403(rid, can_record_meet)
    conn = db.connect()
    conn.execute("DELETE FROM finishers WHERE race_id=?", (rid,))
    conn.execute("UPDATE races SET start_time=NULL, stop_time=NULL WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/races/<int:rid>/untap")
@login_required
def race_untap(rid):
    """Undo the last tap. Won't drop a slot that already has a bib (tap mode)."""
    r, m = _race_or_403(rid, can_record_meet)
    conn = db.connect()
    last = conn.execute("SELECT * FROM finishers WHERE race_id=? ORDER BY seq DESC LIMIT 1",
                        (rid,)).fetchone()
    if not last:
        conn.close()
        return jsonify(ok=True, count=0)
    if last["bib"] is not None and r["capture_mode"] != "scan":
        conn.close()
        return jsonify(error="Last finisher already has a bib — remove it instead"), 400
    conn.execute("DELETE FROM finishers WHERE id=?", (last["id"],))
    conn.commit()
    cnt = conn.execute("SELECT COUNT(*) FROM finishers WHERE race_id=?", (rid,)).fetchone()[0]
    conn.close()
    return jsonify(ok=True, count=cnt)


@bp.post("/races/<int:rid>/finish")
@login_required
def race_finish(rid):
    """Assign a bib. Tap mode: fill the next open (bib-less) slot in order — works
    even after Stop. Scan mode: record a new finisher with the current race time."""
    r, m = _race_or_403(rid, can_record_meet)
    raw = (request.get_json(silent=True) or {}).get("bib")
    try:
        bib = int(str(raw).strip())
    except (TypeError, ValueError):
        return jsonify(error="Bib must be a number"), 400
    if bib <= 0:
        return jsonify(error="Enter a bib number"), 400
    conn = db.connect()
    dup = conn.execute("SELECT snap_name FROM finishers WHERE race_id=? AND bib=?",
                       (rid, bib)).fetchone()
    if dup:
        conn.close()
        nm = f" ({dup['snap_name']})" if dup["snap_name"] else ""
        return jsonify(error=f"Bib {bib}{nm} already recorded"), 400
    a = _athlete_for_bib(conn, m["id"], bib)
    snap = (a["name"] if a else None, a["grade"] if a else None,
            a["gender"] if a else None, a["sname"] if a else None)
    if r["capture_mode"] == "scan":
        start = _parse(r["start_time"])
        if not start or r["stop_time"]:
            conn.close()
            return jsonify(error="Race not running"), 400
        elapsed = (_now() - start).total_seconds()
        seq = (conn.execute("SELECT COALESCE(MAX(seq),0) FROM finishers WHERE race_id=?",
                            (rid,)).fetchone()[0]) + 1
        conn.execute(
            "INSERT INTO finishers (race_id, seq, finish_time, elapsed_seconds, bib, "
            "snap_name, snap_grade, snap_gender, snap_school) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, seq, _iso(_now()), elapsed, bib, *snap))
        remaining = 0
    else:
        slot = conn.execute("SELECT id FROM finishers WHERE race_id=? AND bib IS NULL "
                            "ORDER BY seq LIMIT 1", (rid,)).fetchone()
        if not slot:
            conn.close()
            return jsonify(error="No open slots — tap a finisher first"), 400
        conn.execute("UPDATE finishers SET bib=?, snap_name=?, snap_grade=?, snap_gender=?, "
                     "snap_school=? WHERE id=?", (bib, *snap, slot["id"]))
        remaining = conn.execute("SELECT COUNT(*) FROM finishers WHERE race_id=? AND bib IS NULL",
                                 (rid,)).fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify(ok=True, bib=bib, name=snap[0], school=snap[3], remaining=remaining)


@bp.post("/races/<int:rid>/tap")
@login_required
def race_tap(rid):
    r, m = _race_or_403(rid, can_record_meet)
    start = _parse(r["start_time"])
    if not start:
        return jsonify(error="Race not started"), 400
    elapsed = (_now() - start).total_seconds()
    conn = db.connect()
    seq = (conn.execute("SELECT COALESCE(MAX(seq),0) FROM finishers WHERE race_id=?",
                        (rid,)).fetchone()[0]) + 1
    cur = conn.execute(
        "INSERT INTO finishers (race_id, seq, finish_time, elapsed_seconds) VALUES (?,?,?,?)",
        (rid, seq, _iso(_now()), elapsed))
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify(id=fid, seq=seq, bib=None, elapsed=elapsed, dq=False, name=None, school=None)


@bp.post("/finishers/<int:fid>/bib")
@login_required
def finisher_bib(fid):
    conn = db.connect()
    f = conn.execute("SELECT f.*, r.meet_id FROM finishers f JOIN races r ON r.id=f.race_id "
                     "WHERE f.id=?", (fid,)).fetchone()
    conn.close()
    if not f:
        abort(404)
    _, m = _race_or_403(f["race_id"], can_record_meet)
    raw = (request.get_json(silent=True) or {}).get("bib")
    conn = db.connect()
    if raw in (None, "", "0"):
        conn.execute("UPDATE finishers SET bib=NULL, snap_name=NULL, snap_grade=NULL, "
                     "snap_gender=NULL, snap_school=NULL WHERE id=?", (fid,))
    else:
        bib = int(raw)
        a = _athlete_for_bib(conn, f["meet_id"], bib)
        conn.execute(
            "UPDATE finishers SET bib=?, snap_name=?, snap_grade=?, snap_gender=?, snap_school=? WHERE id=?",
            (bib, a["name"] if a else None, a["grade"] if a else None,
             a["gender"] if a else None, a["sname"] if a else None, fid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/finishers/<int:fid>/dq")
@login_required
def finisher_dq(fid):
    conn = db.connect()
    f = conn.execute("SELECT * FROM finishers WHERE id=?", (fid,)).fetchone()
    conn.close()
    if not f:
        abort(404)
    _race_or_403(f["race_id"], can_record_meet)
    conn = db.connect()
    conn.execute("UPDATE finishers SET dq=? WHERE id=?", (0 if f["dq"] else 1, fid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/finishers/<int:fid>/delete")
@login_required
def finisher_delete(fid):
    conn = db.connect()
    f = conn.execute("SELECT * FROM finishers WHERE id=?", (fid,)).fetchone()
    conn.close()
    if not f:
        abort(404)
    _race_or_403(f["race_id"], can_record_meet)
    conn = db.connect()
    conn.execute("DELETE FROM finishers WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


@bp.post("/races/<int:rid>/reorder")
@login_required
def race_reorder(rid):
    """Reorder runners while times stay in their slots (handoff §8)."""
    r, m = _race_or_403(rid, can_record_meet)
    order = (request.get_json(silent=True) or {}).get("order", [])
    conn = db.connect()
    rows = conn.execute("SELECT * FROM finishers WHERE race_id=? ORDER BY seq", (rid,)).fetchall()
    conn.close()
    if sorted(order) != sorted(f["id"] for f in rows):
        return jsonify(error="order mismatch"), 400
    # Fixed slots: seq + elapsed + finish_time stay; runner payload moves into them.
    slots = [(f["seq"], f["elapsed_seconds"], f["finish_time"]) for f in rows]
    by_id = {f["id"]: f for f in rows}
    conn = db.connect()
    for i, fid in enumerate(order):
        seq, elapsed, ftime = slots[i]
        f = by_id[fid]
        conn.execute(
            "UPDATE finishers SET seq=?, elapsed_seconds=?, finish_time=? WHERE id=?",
            (seq, elapsed, ftime, fid))
    conn.commit()
    conn.close()
    return jsonify(ok=True)


# ------------------------------- scoring -------------------------------
def team_scores(runners):
    """MileSplit/Hy-Tek scoring. `runners` = time-sorted list of dicts with
    keys school, place-eligible. Drops teams <5, re-ranks, sums top 5, tracks
    6th/7th displacers. Returns ranked list of team dicts."""
    by_school = defaultdict(list)
    for r in runners:
        if r["school"]:
            by_school[r["school"]].append(r)
    complete = [s for s, rs in by_school.items() if len(rs) >= 5]
    scoring = [r for r in runners if r["school"] in complete]
    for i, r in enumerate(scoring):
        r["score_place"] = i + 1  # re-ranked among complete-team runners only
    teams = []
    for s in complete:
        rs = [r for r in scoring if r["school"] == s][:7]
        top5 = rs[:5]
        teams.append({
            "school": s,
            "score": sum(r["score_place"] for r in top5),
            "places": [r["score_place"] for r in top5],
            "sixth": rs[5]["score_place"] if len(rs) > 5 else None,
            "seventh": rs[6]["score_place"] if len(rs) > 6 else None,
        })
    teams.sort(key=lambda t: (t["score"], t["sixth"] if t["sixth"] else 9999))
    for i, t in enumerate(teams):
        t["rank"] = i + 1
    return teams


def _meet_finishers(mid):
    conn = db.connect()
    rows = conn.execute(
        "SELECT f.* FROM finishers f JOIN races r ON r.id=f.race_id WHERE r.meet_id=?", (mid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


GENDERS = [("M", "Boys"), ("F", "Girls")]


def build_results(mid):
    """Return {gender_key: {'label','individuals','teams'}} plus 'overall'."""
    fins = [f for f in _meet_finishers(mid)
            if f["elapsed_seconds"] is not None]
    conn = db.connect()
    ts = conn.execute("SELECT team_scoring FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    team_on = bool(ts["team_scoring"]) if ts else True
    out = {}
    groups = {"M": [], "F": [], None: []}
    for f in fins:
        groups.get(f["snap_gender"], groups[None]).append(f)

    def rank_group(items):
        items = sorted(items, key=lambda f: f["elapsed_seconds"])
        indiv = []
        place = 0
        for f in items:
            if not f["dq"]:
                place += 1
                p = place
            else:
                p = None
            indiv.append({
                "place": p, "time": f["elapsed_seconds"], "bib": f["bib"],
                "name": f["snap_name"] or (f"Bib {f['bib']}" if f["bib"] else "—"),
                "school": f["snap_school"], "grade": f["snap_grade"],
                "gender": f["snap_gender"], "dq": bool(f["dq"]),
            })
        scoring_runners = [dict(i) for i in indiv if not i["dq"] and i["school"]]
        teams = team_scores(scoring_runners) if team_on else []
        return indiv, teams

    for key, label in GENDERS:
        indiv, teams = rank_group(groups[key])
        if indiv:
            out[key] = {"label": label, "individuals": indiv, "teams": teams}
    if groups[None]:
        indiv, teams = rank_group(groups[None])
        out["U"] = {"label": "Unspecified", "individuals": indiv, "teams": teams}
    return out


# ------------------------------- results (HTML) -------------------------------
def _results_inner(meet, results, name_mode=None):
    if not results:
        return '<div class="card muted">No results yet.</div>'
    html = []
    for key in ("M", "F", "U"):
        g_ = results.get(key)
        if not g_:
            continue
        rows = "".join(
            f'<tr><td>{"" if i["place"] is None else i["place"]}</td>'
            f'<td>{fmt_time(i["time"])}</td>'
            f'<td>{"" if i["bib"] is None or name_mode else i["bib"]}</td>'
            f'<td>{"<s>" if i["dq"] else ""}{escape(demo.display(i["name"], name_mode))}{" (DQ)" if i["dq"] else ""}{"</s>" if i["dq"] else ""}</td>'
            f'<td>{escape(i["school"] or "")}</td>'
            f'<td>{i["grade"] or ""}</td></tr>'
            for i in g_["individuals"])
        team_rows = "".join(
            f'<tr><td>{t["rank"]}</td><td>{escape(t["school"])}</td>'
            f'<td><b>{t["score"]}</b></td>'
            f'<td class="muted">{" + ".join(str(p) for p in t["places"])}'
            f'{" (" + str(t["sixth"]) + ("," + str(t["seventh"]) if t["seventh"] else "") + ")" if t["sixth"] else ""}</td></tr>'
            for t in g_["teams"])
        team_block = (f'<h3>{g_["label"]} — Team scores</h3>'
                      f'<table><thead><tr><th>Rank</th><th>School</th><th>Score</th>'
                      f'<th>Top 5 (6th,7th)</th></tr></thead><tbody>{team_rows}</tbody></table>'
                      if team_rows else
                      f'<p class="muted">{g_["label"]}: no complete teams (need 5+).</p>')
        html.append(
            f'<div class="card"><h2>{g_["label"]}</h2>'
            f'<table><thead><tr><th>Pl</th><th>Time</th><th>Bib</th><th>Runner</th>'
            f'<th>School</th><th>Gr</th></tr></thead><tbody>{rows}</tbody></table>'
            f'{team_block}</div>')
    return "".join(html)


@bp.get("/meets/<int:mid>/results")
@login_required
def results_page(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    inner = _results_inner(m, build_results(mid), name_mode=demo.mode_for(g.principal))
    body = (f'<p class="muted"><a href="/meets/{mid}">← {escape(m["name"])}</a></p>'
            f'<h1>{escape(m["name"])} — Results</h1>'
            f'{_xc_tabs(mid, "results")}'
            f'<div class="row"><a class="btn ghost" href="/r/{m["public_token"]}" target="_blank">'
            f'Public page ↗</a> <a class="btn ghost" href="/meets/{mid}/results.xlsx">Export xlsx</a></div>'
            f'{inner}')
    return shell(g.principal, body, active="meets")


def _meet_by_token(token):
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE public_token=?", (token,)).fetchone()
    conn.close()
    if not m:
        abort(404)
    return m


def _public_mask(m):
    import json
    conn = db.connect()
    drow = conn.execute("SELECT settings_json FROM districts WHERE id=?",
                        (m["district_id"],)).fetchone()
    conn.close()
    try:
        masked = bool(json.loads((drow["settings_json"] if drow else None) or "{}").get("mask_public"))
    except (ValueError, TypeError):
        masked = False
    return "mask" if masked else None


PUB_CSS = """
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#eef1f5;color:#1b2b3a}
.top{background:#12385f;color:#fff;padding:1rem 1.2rem;display:flex;gap:1rem;align-items:center;justify-content:space-between}
.top .mt{font-size:1.4rem;font-weight:800;line-height:1.15}
.top .sub{opacity:.85;font-size:.85rem;margin-top:.25rem}
.top .right{display:flex;align-items:center;gap:1rem;flex-shrink:0}
.xls{background:#2e8b57;color:#fff;text-decoration:none;font-weight:700;padding:.55rem 1rem;border-radius:9px;white-space:nowrap}
.xls:hover{background:#287a4c}
.qr{text-align:center}
.qr img{width:84px;height:84px;background:#fff;padding:6px;border-radius:8px;display:block}
.qr span{display:block;font-size:.66rem;opacity:.85;margin-top:.2rem}
main{max-width:900px;margin:0 auto;padding:1rem 1rem 3rem}
.tabs{display:flex;gap:.6rem;margin:.4rem 0 1.2rem}
.tab{flex:1;text-align:center;padding:.7rem;border-radius:10px;background:#fff;border:1px solid #d5dde6;font-weight:700;color:#33475b;cursor:pointer;font-size:.95rem}
.tab.on{background:#2f6db5;color:#fff;border-color:#2f6db5}
.sec{background:#fff;border:1px solid #d9e0e8;border-radius:12px;overflow:hidden;margin:0 0 1.1rem}
.sec h2{background:#12385f;color:#fff;margin:0;padding:.6rem 1rem;font-size:1.02rem}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th{background:#f1f4f8;text-align:left;padding:.5rem .8rem;font-size:.7rem;text-transform:uppercase;letter-spacing:.04em;color:#5b6b7c}
td{padding:.55rem .8rem;border-top:1px solid #edf1f5}
tbody tr:nth-child(even) td{background:#f8fafb}
.pl{color:#2f6db5;font-weight:800;text-align:center;width:2.2rem}
.tm{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.mut{color:#7c8b9a;font-size:.85rem}
@media(max-width:600px){
  .top{flex-wrap:wrap;padding:.75rem .8rem;gap:.7rem}
  .top .mt{font-size:1.1rem}
  .top .right{gap:.7rem}
  .xls{padding:.5rem .8rem;font-size:.9rem}
  .qr img{width:58px;height:58px}
  main{padding:.6rem}
  .tabs{gap:.35rem;margin:.3rem 0 .9rem}
  .tab{padding:.6rem .25rem;font-size:.85rem}
  .sec{border-radius:10px;margin-bottom:.8rem}
  .sec h2{font-size:.92rem;padding:.5rem .7rem}
  th{padding:.35rem .45rem;font-size:.6rem}
  td{padding:.45rem .45rem;font-size:.86rem}
}
"""


def _pub_rows(individuals, mode, show_grade):
    out = []
    for i in individuals:
        nm = i["name"]
        if i["bib"] and (not nm or nm == f"Bib {i['bib']}"):
            disp = "Bib not found"
        else:
            disp = demo.display(nm, mode)
        pl = "" if i["place"] is None else i["place"]
        dq = " (DQ)" if i["dq"] else ""
        grcell = f'<td>{i["grade"] or ""}</td>' if show_grade else ""
        out.append(
            f'<tr><td class="pl">{pl}</td>'
            f'<td>{escape(disp)}{dq}</td><td>{escape(i["school"] or "")}</td>'
            f'{grcell}<td class="tm">{fmt_hms(i["time"])}</td></tr>')
    return "".join(out)


def _pub_table(label, individuals, mode, show_grade):
    head = ('<tr><th>Pl</th><th>Name</th><th>School</th>'
            + ('<th>Gr</th>' if show_grade else '') + '<th>Time</th></tr>')
    return (f'<div class="sec"><h2>{escape(label)}</h2><table><thead>{head}</thead>'
            f'<tbody>{_pub_rows(individuals, mode, show_grade)}</tbody></table></div>')


def _grade_gender_groups(mid):
    """Rank finishers within each grade×gender group (for the 'By Grade' tab)."""
    fins = [f for f in _meet_finishers(mid) if f["elapsed_seconds"] is not None]
    buckets = {}
    for f in fins:
        buckets.setdefault((f["snap_grade"], f["snap_gender"]), []).append(f)

    def sk(k):
        grade, gender = k
        return (grade if grade is not None else 999, {"F": 0, "M": 1}.get(gender, 2))

    groups = []
    for key in sorted(buckets, key=sk):
        grade, gender = key
        place = 0
        rows = []
        for f in sorted(buckets[key], key=lambda f: f["elapsed_seconds"]):
            if not f["dq"]:
                place += 1
                p = place
            else:
                p = None
            rows.append({"place": p, "time": f["elapsed_seconds"], "bib": f["bib"],
                         "name": f["snap_name"] or (f"Bib {f['bib']}" if f["bib"] else "—"),
                         "school": f["snap_school"], "grade": f["snap_grade"], "dq": bool(f["dq"])})
        gword = {"F": "Girls", "M": "Boys"}.get(gender, "Other")
        label = f"{grade}th Grade {gword}" if grade is not None else gword
        groups.append((label, rows))
    return groups


def _public_xc(m, mode):
    mid = m["id"]
    results = build_results(mid)
    conn = db.connect()
    races = conn.execute("SELECT start_time, stop_time FROM races WHERE meet_id=?", (mid,)).fetchall()
    conn.close()
    if races and all(r["stop_time"] for r in races):
        status = "Final"
    elif any(r["start_time"] for r in races):
        status = "Live"
    else:
        status = ""

    overall = "".join(
        _pub_table(f"{lbl} Overall", results[key]["individuals"], mode, True)
        for key, lbl in (("F", "Girls"), ("M", "Boys"), ("U", "Other")) if results.get(key)
    ) or '<div class="sec"><h2>No results yet</h2></div>'

    grade = "".join(_pub_table(lbl, rows, mode, False) for lbl, rows in _grade_gender_groups(mid)) \
        or '<div class="sec"><h2>No results yet</h2></div>'

    team_parts = []
    for key, lbl in (("F", "Girls"), ("M", "Boys"), ("U", "Other")):
        g_ = results.get(key)
        if not g_ or not g_["teams"]:
            continue
        trows = "".join(
            f'<tr><td class="pl">{t["rank"]}</td><td>{escape(t["school"])}</td>'
            f'<td class="tm">{t["score"]}</td><td class="mut">'
            f'{" + ".join(str(p) for p in t["places"])}'
            f'{" (" + str(t["sixth"]) + ((", " + str(t["seventh"])) if t["seventh"] else "") + ")" if t["sixth"] else ""}'
            f'</td></tr>' for t in g_["teams"])
        team_parts.append(
            f'<div class="sec"><h2>{lbl} — Team Scores</h2><table><thead>'
            f'<tr><th>Rank</th><th>School</th><th>Score</th><th>Top 5 (6th, 7th)</th></tr>'
            f'</thead><tbody>{trows}</tbody></table></div>')
    team = "".join(team_parts) or '<div class="sec"><h2>No complete teams yet (need 5+ per school)</h2></div>'

    sub = escape(m["date"] or "") + (f" · {status}" if status else "")
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(m['name'])} — Results</title>{HEAD_EXTRA}<style>{PUB_CSS}</style></head><body>
<div class="top">
  <div><div class="mt">{escape(m['name'])} — Combined</div><div class="sub">{sub}</div></div>
</div>
<main>
  <div class="tabs">
    <button class="tab on" id="t-overall" onclick="tab('overall')">📋 Overall</button>
    <button class="tab" id="t-grade" onclick="tab('grade')">🎽 Sorted</button>
    <button class="tab" id="t-team" onclick="tab('team')">🏆 Team</button>
  </div>
  <div id="v-overall">{overall}</div>
  <div id="v-grade" style="display:none">{grade}</div>
  <div id="v-team" style="display:none">{team}</div>
</main>
<script>
function tab(n){{
  ['overall','grade','team'].forEach(function(k){{
    document.getElementById('v-'+k).style.display = k===n?'':'none';
    document.getElementById('t-'+k).className = 'tab'+(k===n?' on':'');
  }});
}}
</script>
</body></html>"""


@bp.get("/r/<token>")
def public_results(token):
    m = _meet_by_token(token)
    mode = _public_mask(m)
    if m["sport"] == "track":
        from . import track  # lazy import avoids a circular import at module load
        inner = track.results_inner(m["id"], name_mode=mode)
        return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(m['name'])} — Results · XCTimer</title><style>{CSS}
main{{max-width:960px;margin:0 auto;padding:1.4rem 1rem 4rem}}
.pubhdr{{display:flex;align-items:center;gap:.6rem;padding:1rem;border-bottom:1px solid var(--line)}}
</style></head><body>
<div class="pubhdr"><span style="font-weight:800;font-size:1.2rem">{BRAND_HTML}</span></div>
<main><h1>{escape(m['name'])}</h1>
<p class="sub">🎽 Track · {escape(m['date'] or '')}</p>
{inner}</main></body></html>"""
    return _public_xc(m, mode)


@bp.get("/r/<token>/results.xlsx")
def public_results_xlsx(token):
    m = _meet_by_token(token)
    return _xlsx_response(m["id"], m["name"], _public_mask(m))


# ------------------------------- xlsx export -------------------------------
def _results_workbook(mid, name_mode):
    """Build the XC results workbook (Boys/Girls/Unspecified tabs). Returns bytes."""
    import openpyxl
    results = build_results(mid)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    any_tab = False
    for title, key in (("Boys", "M"), ("Girls", "F"), ("Unspecified", "U")):
        g_ = results.get(key)
        if not g_:
            continue
        any_tab = True
        ws = wb.create_sheet(title[:31])
        ws.append(["Place", "Time", "Bib", "Runner", "School", "Grade", "Gender"])
        for i in g_["individuals"]:
            ws.append([i["place"], fmt_time(i["time"]), None if name_mode else i["bib"],
                       demo.display(i["name"], name_mode), i["school"], i["grade"], i["gender"]])
        ws.append([])
        ws.append(["Team Rank", "School", "Score", "Top-5 places"])
        for t in g_["teams"]:
            ws.append([t["rank"], t["school"], t["score"],
                       " + ".join(str(p) for p in t["places"])])
    if not any_tab:
        wb.create_sheet("Results").append(["No results yet"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _xlsx_response(mid, name, name_mode):
    fname = (name or "results").replace(" ", "_")
    return Response(_results_workbook(mid, name_mode),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})


@bp.get("/meets/<int:mid>/results.xlsx")
@login_required
def results_xlsx(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    return _xlsx_response(mid, m["name"], demo.mode_for(g.principal))
