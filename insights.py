"""Athlete progress cards + AI Roster Insights chatbot (handoff §8).

- Progress card: an athlete's performance history across meets (XC + track),
  with per-event PRs.
- Insights chatbot: school-scoped (coach) or district-wide (admin) plain-text
  Q&A over a compact data digest. Timers get no insights (handoff §11); demo
  accounts DO (read-only showcase).
"""
from markupsafe import escape
from flask import Blueprint, request, g, abort, jsonify

from . import db, ai, demo
from .auth import login_required
from .tenancy import active_district_id, all_districts
from .ui import shell

bp = Blueprint("insights", __name__)


def _fmt_t(sec):
    if sec is None:
        return ""
    m = int(sec // 60)
    return f"{m}:{sec-60*m:05.2f}" if m else f"{sec:.2f}"


def _districts_for_switcher():
    return all_districts() if g.principal.is_super else None


# ------------------------------- progress card -------------------------------
def _can_access_athlete(a):
    p = g.principal
    if not p or p.role == "timer" or p.meet_scope:
        return False
    conn = db.connect()
    s = conn.execute("SELECT * FROM schools WHERE id=?", (a["school_id"],)).fetchone()
    conn.close()
    if not s:
        return False
    if p.is_super:
        return True
    if p.district_id != s["district_id"]:
        return False
    if p.role == "district_admin":
        return True
    if p.role == "coach":
        return s["id"] in p.school_ids()
    return False


@bp.get("/athletes/<int:aid>/progress")
@login_required
def progress(aid):
    conn = db.connect()
    a = conn.execute("SELECT a.*, s.name AS sname, s.district_id FROM athletes a "
                     "JOIN schools s ON s.id=a.school_id WHERE a.id=?", (aid,)).fetchone()
    if not a:
        conn.close(); abort(404)
    if not _can_access_athlete(a):
        conn.close(); abort(403)

    # Track performances (clean tie via entries.runner_id)
    track_rows = conn.execute(
        "SELECT m.name AS meet, m.date, e.name AS event, e.unit, e.scoring_order, "
        "r.mark_seconds, r.mark_metric, r.place FROM results r "
        "JOIN entries en ON en.id=r.entry_id JOIN meet_events me ON me.id=en.meet_event_id "
        "JOIN events e ON e.id=me.event_id JOIN meets m ON m.id=me.meet_id "
        "WHERE en.runner_id=? AND (r.mark_seconds IS NOT NULL OR r.mark_metric IS NOT NULL) "
        "ORDER BY m.date", (aid,)).fetchall()
    # XC performances (match by bib within the athlete's school, same district)
    xc_rows = conn.execute(
        "SELECT m.name AS meet, m.date, ra.name AS race, f.elapsed_seconds, f.dq "
        "FROM finishers f JOIN races ra ON ra.id=f.race_id JOIN meets m ON m.id=ra.meet_id "
        "WHERE f.bib=? AND f.snap_school=? AND m.district_id=? AND f.elapsed_seconds IS NOT NULL "
        "ORDER BY m.date", (a["bib"], a["sname"], a["district_id"])).fetchall()

    # Season points (track): sum the points-table value at each placed finish
    import json as _json
    default_pt = conn.execute(
        "SELECT id FROM points_tables WHERE name='Invitational 10-8-6-4-2-1'").fetchone()
    ptcache = {}

    def _tbl(pid):
        if pid not in ptcache:
            row = conn.execute("SELECT point_values_json, relay_multiplier FROM points_tables WHERE id=?",
                               (pid,)).fetchone()
            ptcache[pid] = (_json.loads(row["point_values_json"]) if row else [],
                            (row["relay_multiplier"] if row else 1.0) or 1.0)
        return ptcache[pid]

    season_pts = 0.0
    for r in conn.execute(
        "SELECT r.place, m.points_table_id, e.kind FROM results r JOIN entries en ON en.id=r.entry_id "
        "JOIN meet_events me ON me.id=en.meet_event_id JOIN meets m ON m.id=me.meet_id "
        "JOIN events e ON e.id=me.event_id WHERE en.runner_id=? AND r.place IS NOT NULL "
        "AND m.sport='track'", (aid,)).fetchall():
        pid = r["points_table_id"] or (default_pt[0] if default_pt else None)
        vals, mult = _tbl(pid)
        p = r["place"]
        if p and p - 1 < len(vals):
            season_pts += vals[p - 1] * (mult if r["kind"] == "relay" else 1)
    conn.close()

    mode = demo.mode_for(g.principal)
    who = demo.display(a["name"], mode)

    # PRs
    prs = {}  # event -> (best_display, better=min/max)
    perf_rows = []
    for r in xc_rows:
        t = r["elapsed_seconds"]
        perf_rows.append((r["date"], "XC", r["race"] or "Race", _fmt_t(t), r["dq"]))
        key = "XC " + (r["race"] or "")
        if not r["dq"] and (key not in prs or t < prs[key][0]):
            prs[key] = (t, _fmt_t(t))
    for r in track_rows:
        if r["unit"] == "seconds":
            val, disp = r["mark_seconds"], _fmt_t(r["mark_seconds"])
            better_min = True
        else:
            val, disp = r["mark_metric"], (f'{r["mark_metric"]:.2f}m' if r["mark_metric"] else "")
            better_min = False
        perf_rows.append((r["date"], "Track", r["event"], disp, False))
        if val is not None:
            cur = prs.get(r["event"])
            if cur is None or (better_min and val < cur[0]) or (not better_min and val > cur[0]):
                prs[r["event"]] = (val, disp)

    perf_rows.sort(key=lambda x: (x[0] or ""))
    perf_html = "".join(
        f'<tr><td>{escape(d or "")}</td><td>{sp}</td><td>{escape(ev)}</td>'
        f'<td>{"<s>" if dq else ""}{escape(disp)}{"</s>" if dq else ""}</td></tr>'
        for d, sp, ev, disp, dq in perf_rows)
    perf_tbl = (f'<div class="card"><h2>Performances</h2><table><tr><th>Date</th><th>Sport</th>'
                f'<th>Event</th><th>Mark</th></tr>{perf_html}</table></div>'
                if perf_rows else '<div class="card muted">No results recorded yet.</div>')
    pr_html = "".join(f'<tr><td>{escape(ev)}</td><td><b>{escape(d)}</b></td></tr>'
                      for ev, (v, d) in sorted(prs.items()))
    pr_tbl = (f'<div class="card"><h2>Personal records</h2><table><tr><th>Event</th>'
              f'<th>PR</th></tr>{pr_html}</table></div>' if pr_html else "")

    bib = f' · bib {a["bib"]}' if a["bib"] and mode != "anon" else ""
    spts = ("" if not season_pts else
            f' · {int(season_pts) if float(season_pts).is_integer() else round(season_pts, 1)} season pts')
    body = (f'<p class="muted"><a href="/schools/{a["school_id"]}">← Roster</a></p>'
            f'<h1>📈 {escape(who)}</h1>'
            f'<p class="sub">{escape(demo.display(a["sname"], "anon") if mode=="anon" else a["sname"])}'
            f' · grade {a["grade"] or "—"} · {a["gender"] or "—"}{bib}{spts}</p>'
            f'{pr_tbl}{perf_tbl}')
    return shell(g.principal, body, active="", active_district=active_district_id(),
                 districts=_districts_for_switcher())


# ------------------------------- insights chatbot -------------------------------
def _scope(principal):
    """Return (district_id, school_ids or None) for the digest."""
    if principal.role == "coach":
        return principal.district_id, principal.school_ids()
    if principal.is_super:
        return active_district_id(), None  # may be None => all districts
    return principal.district_id, None  # district_admin


def _mark_str(unit, sec, metric):
    """Format a track time or a field feet-inches mark for the digest."""
    if unit == "seconds":
        return _fmt_t(sec)
    if metric is None:
        return ""
    from .track import _fmt_ht  # feet-inches; lazy import avoids a load-time cycle
    return _fmt_ht(metric)


def _athlete_focus(conn, did, school_ids, question, mode):
    """If the question names one or more athletes in scope, return each one's full
    track + XC result history — so 'what is X's 200m time?' can be answered."""
    q = (question or "").lower()
    if len(q) < 3:
        return ""
    if school_ids is not None:
        if not school_ids:
            return ""
        rows = conn.execute(
            f"SELECT a.id, a.name, a.bib, s.name AS sname, s.district_id "
            f"FROM athletes a JOIN schools s ON s.id=a.school_id "
            f"WHERE a.school_id IN ({','.join('?'*len(school_ids))})", tuple(school_ids)).fetchall()
    elif did is not None:
        rows = conn.execute(
            "SELECT a.id, a.name, a.bib, s.name AS sname, s.district_id "
            "FROM athletes a JOIN schools s ON s.id=a.school_id WHERE s.district_id=?", (did,)).fetchall()
    else:
        return ""
    matched = [a for a in rows if a["name"] and a["name"].lower() in q]
    if not matched:  # fall back to a unique last-name match
        by_last = {}
        for a in rows:
            parts = (a["name"] or "").lower().split()
            if parts:
                by_last.setdefault(parts[-1], []).append(a)
        for last, group in by_last.items():
            if len(last) >= 4 and last in q and len(group) == 1:
                matched.append(group[0])
    if not matched:
        return ""
    out = []
    for a in matched[:4]:
        who = demo.display(a["name"], mode)
        trk = conn.execute(
            "SELECT m.name AS meet, m.date, e.name AS event, e.unit, r.mark_seconds, "
            "r.mark_metric, r.place FROM results r JOIN entries en ON en.id=r.entry_id "
            "JOIN meet_events me ON me.id=en.meet_event_id JOIN events e ON e.id=me.event_id "
            "JOIN meets m ON m.id=me.meet_id WHERE en.runner_id=? "
            "AND (r.mark_seconds IS NOT NULL OR r.mark_metric IS NOT NULL) "
            "ORDER BY e.sort, m.date", (a["id"],)).fetchall()
        xc = conn.execute(
            "SELECT m.name AS meet, m.date, ra.name AS race, f.elapsed_seconds "
            "FROM finishers f JOIN races ra ON ra.id=f.race_id JOIN meets m ON m.id=ra.meet_id "
            "WHERE f.bib=? AND f.snap_school=? AND m.district_id=? AND f.elapsed_seconds IS NOT NULL "
            "ORDER BY m.date", (a["bib"], a["sname"], a["district_id"])).fetchall()
        out.append(f"ATHLETE FOCUS — {who} ({a['sname']}):")
        if not trk and not xc:
            out.append("  (no results recorded yet)")
        for r in trk:
            pl = f", place {r['place']}" if r["place"] else ""
            out.append(f"  {r['event']}: {_mark_str(r['unit'], r['mark_seconds'], r['mark_metric'])}"
                       f"{pl} — {r['meet']} ({r['date'] or ''})")
        for r in xc:
            out.append(f"  XC {r['race'] or ''}: {_fmt_t(r['elapsed_seconds'])} — {r['meet']} ({r['date'] or ''})")
        out.append("")
    return "\n".join(out)


def _performance_lists(conn, did, school_ids, mode):
    """Season performance lists: each athlete's BEST mark per event, ranked. This is
    what powers roster-wide 'who's fastest / top 5 / best in X' questions."""
    if did is None:
        return ""
    from .track import _fmt_ht  # feet-inches for field marks
    names = None
    trk_filter, tparams = "", [did]
    if school_ids is not None:
        if not school_ids:
            return ""
        trk_filter = f" AND en.school_id IN ({','.join('?'*len(school_ids))})"
        tparams += list(school_ids)
        names = {r["name"] for r in conn.execute(
            f"SELECT name FROM schools WHERE id IN ({','.join('?'*len(school_ids))})",
            tuple(school_ids)).fetchall()}

    trk = conn.execute(
        "SELECT e.name AS event, e.sort, e.unit, me.gender, me.grade, en.runner_id, "
        "r.mark_seconds, r.mark_metric, r.snap_name, r.snap_school "
        "FROM results r JOIN entries en ON en.id=r.entry_id "
        "JOIN meet_events me ON me.id=en.meet_event_id JOIN events e ON e.id=me.event_id "
        "JOIN meets m ON m.id=me.meet_id "
        "WHERE m.district_id=? AND m.sport='track' AND en.runner_id IS NOT NULL "
        "AND (r.mark_seconds IS NOT NULL OR r.mark_metric IS NOT NULL)" + trk_filter,
        tuple(tparams)).fetchall()
    groups = {}  # (sort, event, gender, grade) -> {runner_id: (val, is_time, name, school)}
    for r in trk:
        is_time = r["unit"] == "seconds"
        val = r["mark_seconds"] if is_time else r["mark_metric"]
        if val is None:
            continue
        g = groups.setdefault((r["sort"] or 0, r["event"], r["gender"] or "", r["grade"]), {})
        cur = g.get(r["runner_id"])
        if cur is None or (is_time and val < cur[0]) or (not is_time and val > cur[0]):
            g[r["runner_id"]] = (val, is_time, r["snap_name"], r["snap_school"])

    def _div(gender, grade):
        gw = {"M": "Boys", "F": "Girls"}.get(gender, "")
        return (f"{gw} {grade}th".strip() if grade else (gw or "Open"))

    lines = []
    if groups:
        lines.append("=== SEASON PERFORMANCE LISTS — TRACK (each athlete's best mark, ranked) ===")
    for key in sorted(groups):
        _s, event, gender, grade = key
        ents = list(groups[key].values())
        is_time = ents[0][1]
        ents.sort(key=lambda x: x[0], reverse=not is_time)
        parts = [f"{i}) {demo.display(nm or '?', mode)} ({sch or '?'}) "
                 f"{_fmt_t(v) if is_t else _fmt_ht(v)}"
                 for i, (v, is_t, nm, sch) in enumerate(ents[:30], 1)]
        lines.append(f"{event} — {_div(gender, grade)}: " + "; ".join(parts))

    xc = conn.execute(
        "SELECT f.snap_grade AS grade, f.snap_gender AS gender, f.bib, f.snap_name, "
        "f.snap_school, f.elapsed_seconds FROM finishers f JOIN races ra ON ra.id=f.race_id "
        "JOIN meets m ON m.id=ra.meet_id WHERE m.district_id=? AND f.dq=0 "
        "AND f.elapsed_seconds IS NOT NULL", (did,)).fetchall()
    xg = {}
    for r in xc:
        if names is not None and r["snap_school"] not in names:
            continue
        g = xg.setdefault((r["grade"], r["gender"] or ""), {})
        akey = (r["bib"], r["snap_school"])
        if akey not in g or r["elapsed_seconds"] < g[akey][0]:
            g[akey] = (r["elapsed_seconds"], r["snap_name"], r["snap_school"])
    if xg:
        lines.append("=== SEASON PERFORMANCE LISTS — CROSS COUNTRY (best time, ranked) ===")
    for key in sorted(xg, key=lambda k: (k[0] if k[0] is not None else 999,
                                         {"F": 0, "M": 1}.get(k[1], 2))):
        grade, gender = key
        ents = sorted(xg[key].values(), key=lambda x: x[0])
        parts = [f"{i}) {demo.display(nm or '?', mode)} ({sch or '?'}) {_fmt_t(v)}"
                 for i, (v, nm, sch) in enumerate(ents[:30], 1)]
        lines.append(f"XC — {_div(gender, grade)}: " + "; ".join(parts))
    return "\n".join(lines)


def _digest(principal, question=""):
    did, school_ids = _scope(principal)
    mode = demo.mode_for(principal)
    conn = db.connect()
    lines = []
    if principal.is_super and did is None:
        lines.append("SCOPE: all districts (platform overview)")
        for d in conn.execute("SELECT * FROM districts ORDER BY name").fetchall():
            sc = conn.execute("SELECT COUNT(*) FROM schools WHERE district_id=?", (d["id"],)).fetchone()[0]
            at = conn.execute("SELECT COUNT(*) FROM athletes a JOIN schools s ON s.id=a.school_id "
                              "WHERE s.district_id=?", (d["id"],)).fetchone()[0]
            lines.append(f"- District {d['name']}: {sc} schools, {at} athletes")
        conn.close()
        return "\n".join(lines)

    d = conn.execute("SELECT name FROM districts WHERE id=?", (did,)).fetchone()
    lines.append(f"DISTRICT: {d['name'] if d else did}")

    # Named-athlete history first — most specific to the question, so it survives truncation.
    focus = _athlete_focus(conn, did, school_ids, question, mode)
    if focus:
        lines.append("\n" + focus)

    # District record board (so it survives truncation) — key for
    # "what's the district record for the 100m?" questions.
    recs = conn.execute(
        "SELECT gender, grade, event, mark, athlete, school, year FROM district_records "
        "WHERE district_id=? ORDER BY event, gender, grade", (did,)).fetchall()
    if recs:
        lines.append("\nDISTRICT RECORDS (best mark per event × grade × gender; "
                     "for an event's overall record, take the fastest time / longest "
                     "distance / highest jump across grades):")
        for r in recs:
            lines.append(f"  {r['event']} | {r['gender']} {r['grade']} | {r['mark']} | "
                         f"{r['athlete']} ({r['school']}, {r['year']})")
        lines.append("")

    # Ranked performance lists — powers roster-wide 'who's fastest / top N / best in X'.
    perf = _performance_lists(conn, did, school_ids, mode)
    if perf:
        lines.append(perf)
        lines.append("")
    if school_ids is not None:
        schools = conn.execute(
            f"SELECT * FROM schools WHERE id IN ({','.join('?'*len(school_ids))})",
            tuple(school_ids)).fetchall() if school_ids else []
        lines.append("SCOPE: coach — schools: " + ", ".join(s["name"] for s in schools))
    else:
        schools = conn.execute("SELECT * FROM schools WHERE district_id=? ORDER BY name", (did,)).fetchall()

    for s in schools:
        ath = conn.execute("SELECT name, grade, gender FROM athletes WHERE school_id=? ORDER BY name",
                           (s["id"],)).fetchall()
        b = sum(1 for x in ath if x["gender"] == "M")
        gcnt = sum(1 for x in ath if x["gender"] == "F")
        lines.append(f"\nSCHOOL {s['name']}: {len(ath)} athletes ({b} boys, {gcnt} girls)")
        for x in ath[:40]:
            nm = demo.display(x["name"], mode)
            lines.append(f"  - {nm}, grade {x['grade'] or '?'}, {x['gender'] or '?'}")

    # Recent meets + a few results
    meets = conn.execute("SELECT * FROM meets WHERE district_id=? ORDER BY date DESC LIMIT 6",
                         (did,)).fetchall()
    for m in meets:
        lines.append(f"\nMEET {m['name']} ({m['sport']}, {m['date']}):")
        if m["sport"] == "xc":
            fin = conn.execute(
                "SELECT f.elapsed_seconds, f.snap_name, f.snap_school FROM finishers f "
                "JOIN races ra ON ra.id=f.race_id WHERE ra.meet_id=? AND f.dq=0 "
                "AND f.elapsed_seconds IS NOT NULL ORDER BY f.elapsed_seconds LIMIT 8", (m["id"],)).fetchall()
            for i, r in enumerate(fin):
                lines.append(f"  {i+1}. {demo.display(r['snap_name'] or '?', mode)} "
                             f"({r['snap_school'] or '?'}) {_fmt_t(r['elapsed_seconds'])}")
        else:
            rr = conn.execute(
                "SELECT e.name AS ev, r.place, r.mark_seconds, r.mark_metric, r.snap_name, r.snap_school "
                "FROM results r JOIN entries en ON en.id=r.entry_id JOIN meet_events me ON me.id=en.meet_event_id "
                "JOIN events e ON e.id=me.event_id WHERE me.meet_id=? AND r.place=1 LIMIT 12", (m["id"],)).fetchall()
            for r in rr:
                mk = _fmt_t(r["mark_seconds"]) if r["mark_seconds"] is not None else \
                    (f'{r["mark_metric"]:.2f}m' if r["mark_metric"] else "")
                lines.append(f"  {r['ev']} winner: {demo.display(r['snap_name'] or '?', mode)} "
                             f"({r['snap_school'] or '?'}) {mk}")
    conn.close()
    text = "\n".join(lines)
    return text[:60000]


_SYS = ("You are XCTimer's roster insights assistant for a school running program. "
        "Answer the coach/admin's question using ONLY the data digest provided. Be concise "
        "and factual; give plain text (no markdown tables). The digest includes SEASON "
        "PERFORMANCE LISTS — each athlete's best mark per event, already ranked (fastest "
        "time / longest distance / highest jump first) and grouped by event × gender × grade; "
        "use them for 'who is fastest', 'top N', and 'best in <event>' questions, and to rank "
        "across grades, compare the per-grade lists. Times are M:SS.xx; field marks are "
        "feet-inches (e.g. 15-06). If the data doesn't contain the answer, say so briefly. "
        "Never invent athletes, times, or results.")


@bp.get("/insights")
@login_required
def insights_page():
    p = g.principal
    if p.role == "timer" or p.meet_scope:
        abort(403)
    scope_lbl = ("your schools" if p.role == "coach"
                 else "all districts" if (p.is_super and active_district_id() is None)
                 else "this district")
    body = f"""
<h1>AI Roster Insights</h1>
<p class="sub">Ask about {escape(scope_lbl)} — rosters, meet results, PRs. Answers use your data only.</p>
<div class="card">
  <div id="log" style="min-height:60px"></div>
  <div class="row" style="margin-top:.6rem">
    <div style="flex:1"><input id="q" placeholder="e.g. Who are my fastest boys this season?"
      onkeydown="if(event.key==='Enter')ask()"></div>
    <div style="display:flex;align-items:flex-end"><button onclick="ask()">Ask</button></div>
  </div>
</div>
<div class="card muted">Examples: “Who's my fastest 200m runner?” · “Top 5 girls in the 1600m” ·
“What's Grayson Young's 200m time?” · “Which school has the best shot put?” ·
“What's the district record for the 100m?”</div>
<script>
async function ask(){{
  const q=document.getElementById('q').value.trim(); if(!q)return;
  const log=document.getElementById('log');
  log.innerHTML+='<p><b>You:</b> '+esc(q)+'</p><p class="muted" id="pend">Thinking…</p>';
  document.getElementById('q').value='';
  try{{ const j=await jpost('/api/insights/ask',{{question:q}});
    document.getElementById('pend').outerHTML='<p><b>Insights:</b> '+esc(j.answer).replace(/\\n/g,'<br>')+'</p>'; }}
  catch(e){{ document.getElementById('pend').outerHTML='<p class="msg err">'+esc(e.message)+'</p>'; }}
  log.scrollTop=log.scrollHeight;
}}
</script>"""
    return shell(p, body, active="insights", active_district=active_district_id(),
                 districts=_districts_for_switcher())


@bp.post("/api/insights/ask")
@login_required
def insights_ask():
    p = g.principal
    if p.role == "timer" or p.meet_scope:
        abort(403)
    q = (request.get_json(silent=True) or {}).get("question", "").strip()
    if not q:
        return jsonify(error="Ask a question"), 400
    try:
        digest = _digest(p, q)
        answer = ai.claude_chat(_SYS, f"DATA DIGEST:\n{digest}\n\nQUESTION: {q}", max_tokens=1000)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Insights unavailable: {e}"), 500
    return jsonify(answer=answer)
