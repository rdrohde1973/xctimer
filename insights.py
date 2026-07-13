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
    body = (f'<p class="muted"><a href="/schools/{a["school_id"]}">← Roster</a></p>'
            f'<h1>📈 {escape(who)}</h1>'
            f'<p class="sub">{escape(demo.display(a["sname"], "anon") if mode=="anon" else a["sname"])}'
            f' · grade {a["grade"] or "—"} · {a["gender"] or "—"}{bib}</p>'
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


def _digest(principal):
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

    # District record board first (so it survives truncation) — key for
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
    return text[:12000]


_SYS = ("You are XCTimer's roster insights assistant for a school running program. "
        "Answer the coach/admin's question using ONLY the data digest provided. Be concise "
        "and factual; give plain text (no markdown tables). If the data doesn't contain the "
        "answer, say so briefly. Never invent athletes, times, or results.")


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
<div class="card muted">Examples: “What's the district record for the 100m?” · “Which school has the most girls?”
· “Top 3 in the 100m at the last meet?” · “Who improved the most?”</div>
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
        digest = _digest(p)
        answer = ai.claude_chat(_SYS, f"DATA DIGEST:\n{digest}\n\nQUESTION: {q}", max_tokens=1000)
    except Exception as e:  # noqa: BLE001
        return jsonify(error=f"Insights unavailable: {e}"), 500
    return jsonify(answer=answer)
