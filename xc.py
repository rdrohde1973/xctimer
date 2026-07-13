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
from .ui import shell, BRAND_HTML, CSS
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


# ------------------------------- races -------------------------------
@bp.post("/meets/<int:mid>/races")
@login_required
def create_race(mid):
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    name = (request.form.get("name") or "").strip()
    if not name:
        abort(400)
    conn = db.connect()
    conn.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)",
                 (mid, name, "tap"))
    conn.commit()
    conn.close()
    return redirect(f"/meets/{mid}")


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


# ------------------------------- timing console -------------------------------
@bp.get("/races/<int:rid>/console")
@login_required
def console(rid):
    r, m = _race_or_403(rid, can_record_meet)
    body = f"""
<p class="muted"><a href="/meets/{m['id']}">← {escape(m['name'])}</a></p>
<h1>{escape(r['name'])}</h1>
<div class="card" style="text-align:center">
  <div id="clock" style="font-size:3rem;font-weight:800;font-variant-numeric:tabular-nums">0:00.0</div>
  <div style="margin:.8rem 0">
    <button id="startbtn" onclick="startRace()">Start</button>
    <button id="stopbtn" class="ghost" onclick="stopRace()">Stop</button>
  </div>
  <button id="tapbtn" onclick="tap()" disabled
    style="font-size:1.6rem;padding:1.2rem 2rem;width:100%;max-width:420px">TAP finisher</button>
</div>
<div class="card"><h2>Finishers (<span id="count">0</span>)</h2>
  <table><thead><tr><th>#</th><th>Time</th><th>Bib</th><th>Runner</th><th></th></tr></thead>
  <tbody id="rows"></tbody></table>
</div>
<script>
const RID={rid};
let OFFSET=0, START=null, STOPMS=null, STOPPED=false, FIN=[];
function nowms(){{ return Date.now()+OFFSET; }}
function fmt(sec){{ const m=Math.floor(sec/60); const s=(sec-60*m);
  return m+':'+s.toFixed(1).padStart(4,'0'); }}
async function load(){{
  const s=await jget('/races/'+RID+'/state');
  OFFSET=s.server_ms-Date.now(); START=s.start_ms; STOPMS=s.stop_ms; STOPPED=s.stopped; FIN=s.finishers;
  document.getElementById('tapbtn').disabled = !START || STOPPED;
  document.getElementById('startbtn').textContent = START? 'Restart' : 'Start';
  render();
}}
function tick(){{
  if(!START){{ document.getElementById('clock').textContent='0:00.0'; return; }}
  const end = (STOPPED && STOPMS) ? STOPMS : nowms();
  let e=(end-START)/1000; if(e<0)e=0;
  document.getElementById('clock').textContent=fmt(e);
}}
function render(){{
  document.getElementById('count').textContent=FIN.length;
  let h='';
  FIN.forEach((f,i)=>{{
    h+='<tr><td>'+f.seq+'</td><td>'+fmt(f.elapsed)+'</td>'
     +'<td><input value="'+(f.bib??'')+'" style="width:70px" '
     +'onchange="setBib('+f.id+',this.value)"></td>'
     +'<td>'+(f.dq?'<s>':'' )+esc(f.name||'')+(f.name?(' <span class=muted>'+esc(f.school||'')+'</span>'):'')+(f.dq?'</s>':'')+'</td>'
     +'<td style="text-align:right;white-space:nowrap">'
     +'<button class="ghost" onclick="move('+i+',-1)">↑</button> '
     +'<button class="ghost" onclick="move('+i+',1)">↓</button> '
     +'<button class="ghost" onclick="dq('+f.id+')">'+(f.dq?'un-DQ':'DQ')+'</button> '
     +'<button class="danger" onclick="del('+f.id+')">✕</button></td></tr>';
  }});
  document.getElementById('rows').innerHTML=h;
}}
async function startRace(){{ await jpost('/races/'+RID+'/start',{{}}); load(); }}
async function stopRace(){{ await jpost('/races/'+RID+'/stop',{{}}); load(); }}
async function tap(){{ const f=await jpost('/races/'+RID+'/tap',{{}}); FIN.push(f); render(); }}
async function setBib(id,v){{ await jpost('/finishers/'+id+'/bib',{{bib:v}}); load(); }}
async function dq(id){{ await jpost('/finishers/'+id+'/dq',{{}}); load(); }}
async function del(id){{ if(!confirm('Delete finisher?'))return; await jpost('/finishers/'+id+'/delete',{{}}); load(); }}
async function move(i,d){{ const j=i+d; if(j<0||j>=FIN.length)return;
  const order=FIN.map(f=>f.id); [order[i],order[j]]=[order[j],order[i]];
  await jpost('/races/'+RID+'/reorder',{{order}}); load(); }}
setInterval(tick,100); load();
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
        "elapsed": f["elapsed_seconds"], "dq": bool(f["dq"]),
        "name": f["snap_name"], "school": f["snap_school"],
    } for f in rows]
    return jsonify(
        name=r["name"],
        start_ms=_ms(start) if start else None,
        stop_ms=_ms(stop) if stop else None,
        stopped=bool(r["stop_time"]),
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
        teams = team_scores(scoring_runners)
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
            f'<div class="row"><a class="btn ghost" href="/r/{m["public_token"]}" target="_blank">'
            f'Public page ↗</a> <a class="btn ghost" href="/meets/{mid}/results.xlsx">Export xlsx</a></div>'
            f'{inner}')
    return shell(g.principal, body, active="meets")


@bp.get("/r/<token>")
def public_results(token):
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE public_token=?", (token,)).fetchone()
    conn.close()
    if not m:
        abort(404)
    import json
    conn = db.connect()
    drow = conn.execute("SELECT settings_json FROM districts WHERE id=?",
                        (m["district_id"],)).fetchone()
    conn.close()
    try:
        masked = bool(json.loads((drow["settings_json"] if drow else None) or "{}").get("mask_public"))
    except (ValueError, TypeError):
        masked = False
    mode = "mask" if masked else None
    if m["sport"] == "track":
        from . import track  # lazy import avoids a circular import at module load
        inner = track.results_inner(m["id"], name_mode=mode)
    else:
        inner = _results_inner(m, build_results(m["id"]), name_mode=mode)
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(m['name'])} — Results · XCTimer</title><style>{CSS}
main{{max-width:960px;margin:0 auto;padding:1.4rem 1rem 4rem}}
.pubhdr{{display:flex;align-items:center;gap:.6rem;padding:1rem;border-bottom:1px solid var(--line)}}
</style></head><body>
<div class="pubhdr"><span style="font-weight:800;font-size:1.2rem">{BRAND_HTML}</span></div>
<main><h1>{escape(m['name'])}</h1>
<p class="sub">{"🏃 Cross-country" if m['sport']=='xc' else "🏟️ Track"} · {escape(m['date'] or '')}</p>
{inner}</main></body></html>"""


# ------------------------------- xlsx export -------------------------------
@bp.get("/meets/<int:mid>/results.xlsx")
@login_required
def results_xlsx(mid):
    m = load_meet(mid)
    if not can_view_meet(m):
        abort(403)
    import openpyxl
    results = build_results(mid)
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    tabs = [("Boys", "M"), ("Girls", "F"), ("Unspecified", "U")]
    any_tab = False
    for title, key in tabs:
        g_ = results.get(key)
        if not g_:
            continue
        any_tab = True
        ws = wb.create_sheet(title[:31])
        nm = demo.mode_for(g.principal)
        ws.append(["Place", "Time", "Bib", "Runner", "School", "Grade", "Gender"])
        for i in g_["individuals"]:
            ws.append([i["place"], fmt_time(i["time"]), None if nm else i["bib"],
                       demo.display(i["name"], nm), i["school"], i["grade"], i["gender"]])
        ws.append([])
        ws.append(["Team Rank", "School", "Score", "Top-5 places"])
        for t in g_["teams"]:
            ws.append([t["rank"], t["school"], t["score"],
                       " + ".join(str(p) for p in t["places"])])
    if not any_tab:
        wb.create_sheet("Results").append(["No results yet"])
    buf = io.BytesIO()
    wb.save(buf)
    fname = (m["name"] or "results").replace(" ", "_")
    return Response(buf.getvalue(),
                    mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'})
