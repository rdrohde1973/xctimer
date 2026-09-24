"""Championship picks: the 7 fastest per school per grade x gender, fairly compared.

Times from different courses cannot be compared raw -- a hilly course is slower for
everyone. So every XC result in the database feeds one additive model on log-time:

    log(time) = ability[runner] + difficulty[race]

fitted by alternating means. A race's difficulty is learned from the runners who ran
it AND something else, which is why it works: 96 runners linked the five meets of
September 2026, 18-39 shared runners per pair. The fitted ability, turned back into
a time, is "what this runner would run on an average course". The model uses each
RACE, not each meet, so a meet where boys and girls ran different distances is fine.

Ranking is deterministic and explainable. Only the close calls around the 7th/8th
cut -- the toss-ups -- go to the LLM, with the evidence: adjusted times, every raw
result with its date, and who beat whom when they ran the same race. Head-to-head
is also the deterministic fallback when the LLM is unavailable.

Everything here SUGGESTS. Nothing is written until a coach presses Apply, and they
can change any pick first.
"""
import json
import math
import time
from collections import defaultdict

from . import db

PICKS = 7              # runners per school per grade x gender
TOSSUP_PCT = 0.02      # within 2% of the 7th/8th line (~19s over 16 min) is a toss-up
ALTERNATES = 3         # shown under the picks
_ITER = 200
_CACHE, _CACHE_TTL = {}, 1800   # LLM answers per (school, data fingerprint), 30 min


# ------------------------------------------------------------------ data
def _results(conn):
    """Every timed, non-DQ XC result, resolved to an athlete through meet_bibs."""
    return conn.execute(
        "SELECT mb.athlete_id AS aid, a.name, a.grade, a.gender, a.school_id AS sid, "
        "       ra.id AS rid, ra.name AS race, m.id AS mid, m.name AS meet, m.date, "
        "       f.elapsed_seconds AS t "
        "FROM meet_bibs mb "
        "JOIN races ra ON ra.meet_id=mb.meet_id "
        "JOIN finishers f ON f.race_id=ra.id AND f.bib=mb.bib "
        "JOIN meets m ON m.id=ra.meet_id "
        "JOIN athletes a ON a.id=mb.athlete_id "
        "WHERE m.sport='xc' AND f.elapsed_seconds > 0 AND COALESCE(f.dq,0)=0").fetchall()


def fit(rows):
    """Alternating means on log-time. Returns (ability{aid}, difficulty{rid})."""
    ab, df = {}, defaultdict(float)
    by_a, by_r = defaultdict(list), defaultdict(list)
    for r in rows:
        lt = math.log(r["t"])
        by_a[r["aid"]].append((r["rid"], lt))
        by_r[r["rid"]].append((r["aid"], lt))
    groups = _components(by_a, by_r)
    for _ in range(_ITER):
        ab = {a: sum(lt - df[rid] for rid, lt in xs) / len(xs) for a, xs in by_a.items()}
        new = {rid: sum(lt - ab[a] for a, lt in xs) / len(xs) for rid, xs in by_r.items()}
        # Only differences are identified, and only WITHIN a group of races linked by
        # shared runners. Pin each group's average race to zero so an ability turns
        # back into a time on that group's typical course.
        df = defaultdict(float)
        for g in groups:
            mean = sum(new[r] for r in g) / len(g)
            for r in g:
                df[r] = new[r] - mean
    return ab, dict(df)


def _components(by_a, by_r):
    """Groups of races connected through runners who ran more than one of them."""
    seen, groups = set(), []
    for start in by_r:
        if start in seen:
            continue
        stack, g = [start], []
        seen.add(start)
        while stack:
            r = stack.pop()
            g.append(r)
            for a, _lt in by_r[r]:
                for r2, _ in by_a[a]:
                    if r2 not in seen:
                        seen.add(r2)
                        stack.append(r2)
        groups.append(g)
    return groups


def course_table(rows, df):
    """Per race: how much slower/faster than the average course FOR THAT GENDER.

    Boys' and girls' races are only tied together through the few runners in a mixed
    heat, so one shared average made "Lehi Girls +1% / Lehi Boys -17%" appear for the
    same course -- true to the model, meaningless to a reader. Selection only ever
    compares within a gender, so the display does too.
    """
    seen, sexes = {}, defaultdict(lambda: defaultdict(int))
    for r in rows:
        seen.setdefault(r["rid"], (r["meet"], r["race"], r["date"]))
        sexes[r["rid"]][r["gender"] or "?"] += 1
    group = {rid: max(sx, key=sx.get) for rid, sx in sexes.items()}
    base = {}
    for gx in set(group.values()):
        ids = [rid for rid in seen if group[rid] == gx]
        base[gx] = sum(df.get(rid, 0.0) for rid in ids) / len(ids)
    word = {"M": "Boys", "F": "Girls"}
    return sorted(({"rid": rid, "meet": v[0], "race": v[1], "date": v[2],
                    "group": word.get(group[rid], "Other"),
                    "pct": (math.exp(df.get(rid, 0.0) - base[group[rid]]) - 1) * 100}
                   for rid, v in seen.items()),
                  key=lambda x: (x["group"], x["date"] or ""))


def _h2h(rows, ids):
    """wins[a][b] = number of races a and b both ran where a finished first."""
    by_race = defaultdict(dict)
    for r in rows:
        if r["aid"] in ids:
            by_race[r["rid"]][r["aid"]] = r["t"]
    wins = defaultdict(lambda: defaultdict(int))
    for times in by_race.values():
        xs = list(times.items())
        for i in range(len(xs)):
            for j in range(len(xs)):
                if i != j and xs[i][1] < xs[j][1]:
                    wins[xs[i][0]][xs[j][0]] += 1
    return wins


# ------------------------------------------------------------------ selection
def suggest(school_id, use_llm=True):
    """Suggested picks for one school, every grade x gender. Never writes anything."""
    conn = db.connect()
    rows = _results(conn)
    roster = conn.execute(
        "SELECT id, name, grade, gender, does_champ FROM athletes "
        "WHERE school_id=? AND active=1 AND does_xc=1", (school_id,)).fetchall()
    conn.close()
    ab, df = fit(rows) if rows else ({}, {})
    mine = defaultdict(list)
    for r in rows:
        if r["sid"] == school_id:
            mine[r["aid"]].append(r)

    cats, uncategorised = defaultdict(list), []
    for a in roster:
        if a["grade"] is None or a["gender"] not in ("M", "F"):
            uncategorised.append(dict(a))
            continue
        res = sorted(mine.get(a["id"], []), key=lambda r: r["date"] or "")
        cats[(a["grade"], a["gender"])].append({
            "aid": a["id"], "name": a["name"], "picked_now": bool(a["does_champ"]),
            "rating": math.exp(ab[a["id"]]) if a["id"] in ab else None,
            "n": len(res),
            "results": [{"meet": r["meet"], "race": r["race"], "date": r["date"], "t": r["t"],
                         "adj": r["t"] / math.exp(df.get(r["rid"], 0.0))} for r in res],
        })

    out, tossups = [], []
    for (gr, gx) in sorted(cats, key=lambda k: (k[0], 0 if k[1] == "F" else 1)):
        people = cats[(gr, gx)]
        ranked = sorted((p for p in people if p["rating"] is not None), key=lambda p: p["rating"])
        unranked = sorted((p for p in people if p["rating"] is None), key=lambda p: p["name"])
        cat = {"grade": gr, "gender": gx, "label": f'{gr}th {"Girls" if gx == "F" else "Boys"}',
               "ranked": ranked, "unranked": unranked, "picks": [], "tossup": None}
        if len(ranked) <= PICKS:
            cat["picks"] = [(p, "clear") for p in ranked]
        else:
            line = (ranked[PICKS - 1]["rating"] + ranked[PICKS]["rating"]) / 2
            zone = [p for p in ranked if abs(p["rating"] - line) / line <= TOSSUP_PCT]
            if not zone or ranked[PICKS - 1] not in zone or ranked[PICKS] not in zone:
                cat["picks"] = [(p, "clear") for p in ranked[:PICKS]]     # a clean gap
            else:
                clear = [p for p in ranked[:PICKS] if p not in zone]
                slots = PICKS - len(clear)
                ids = {p["aid"] for p in zone}
                wins = _h2h(rows, ids)
                for p in zone:
                    p["h2h"] = {q["name"]: [wins[p["aid"]][q["aid"]], wins[q["aid"]][p["aid"]]]
                                for q in zone if q is not p
                                and (wins[p["aid"]][q["aid"]] or wins[q["aid"]][p["aid"]])}
                # Deterministic order: net head-to-head wins inside the zone, then rating.
                order = sorted(zone, key=lambda p: (
                    -sum(wins[p["aid"]][q["aid"]] - wins[q["aid"]][p["aid"]] for q in zone if q is not p),
                    p["rating"]))
                chosen, left = order[:slots], order[slots:]
                # Settled outright when every pick beat every runner left out, in a race
                # they both ran. That needs no judgement, so it never goes to the LLM --
                # which only sees the real close calls: runners who never met, or who
                # have split results.
                settled = all(wins[a["aid"]][b["aid"]] > wins[b["aid"]][a["aid"]]
                              for a in chosen for b in left)
                cat["picks"] = [(p, "clear") for p in clear]
                cat["tossup"] = {"zone": zone, "slots": slots, "order": order,
                                 "chosen": chosen, "why": {}, "settled": settled,
                                 "by": "head-to-head"}
                if not settled:
                    tossups.append(cat)
        picked = {p["aid"] for p, _ in cat["picks"]}
        cat["alternates"] = [p for p in ranked if p["aid"] not in picked][:ALTERNATES]
        out.append(cat)

    note = None
    if tossups and use_llm:
        note = _resolve_with_llm(school_id, tossups)
    for cat in out:
        tu = cat["tossup"]
        if tu:
            cat["picks"] += [(p, "tossup") for p in tu["chosen"]]
            chosen = {p["aid"] for p in tu["chosen"]}
            left = [p for p in tu["order"] if p["aid"] not in chosen]
            rest = [p for p in cat["ranked"] if p["aid"] not in {x["aid"] for x, _ in cat["picks"]}
                    and p not in left]
            cat["alternates"] = (left + rest)[:ALTERNATES]
        cat["picks"].sort(key=lambda pr: pr[0]["rating"])
    return {"categories": out, "uncategorised": uncategorised,
            "courses": course_table(rows, df), "llm_note": note,
            "bridges": sum(1 for a in {r["aid"] for r in rows}
                           if len({r["rid"] for r in rows if r["aid"] == a}) > 1) if rows else 0}


# ------------------------------------------------------------------ LLM toss-ups
_SYS = (
    "You help a junior-high cross country coach choose runners for a championship race. "
    "For each group below, the clear picks are already made. You are deciding only the "
    "remaining slots among runners whose course-adjusted times are within about 2% of "
    "each other, which is too close for the times alone to settle.\n\n"
    "Evidence per runner: an adjusted time (their typical time on an average course, "
    "after removing how hard each course was), how many races it rests on, every raw "
    "result with its date and the course-adjusted equivalent, and head-to-head records "
    "against the others in the group from races they ran together.\n\n"
    "Weigh the evidence like an experienced coach. Finishing ahead of someone in the same "
    "race is strong evidence because it involves no course adjustment at all, and the most "
    "recent shared race matters most. Recent form matters more than early-season results. "
    "A rating built on one race is less certain than one built on three. When one race is "
    "flagged as out of line with a runner's others, consider that it may have been an off "
    "day that drags their average down rather than their true level.\n\n"
    "Choose exactly the number of runners asked for, using only the ids given. Then write "
    "each group a reason of one or two sentences that a coach could read to a parent. "
    "Every time and every who-beat-whom you mention must match the evidence exactly; check "
    "each one before you write it, and never describe a race as supporting your choice if "
    "the runner you left out finished ahead in it.")

_SCHEMA = {
    "type": "object",
    "properties": {"groups": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "group": {"type": "string"},
            "chosen_ids": {"type": "array", "items": {"type": "integer"}},
            "reason": {"type": "string"},
        },
        "required": ["group", "chosen_ids", "reason"],
        "additionalProperties": False}}},
    "required": ["groups"],
    "additionalProperties": False,
}


def _mmss(s):
    return "%d:%04.1f" % (int(s // 60), s % 60)


OFF_DAY = 0.08   # a race this far (8%) from a runner's other adjusted times is out of line


def _off_days(p):
    """Indexes of results out of line with the runner's others (needs 3+ to tell which)."""
    adj = [r["adj"] for r in p["results"]]
    if len(adj) < 3:
        return set()
    # Median of ALL their races: with three or more, one bad race cannot move it. (The
    # median of the OTHER races, tried first, averages the outlier into the baseline
    # when there are only three, and then flags the good races too.)
    srt = sorted(adj)
    n = len(srt)
    mid = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {i for i, a in enumerate(adj) if abs(a - mid) / mid > OFF_DAY}


def _evidence(cat):
    tu = cat["tossup"]
    zone = tu["zone"]
    lines = [f'GROUP "{cat["label"]}": choose {tu["slots"]} of these {len(zone)}.']
    for p in zone:
        off = _off_days(p)
        res = "; ".join(f'{r["date"]} {r["meet"]} ({r["race"]}): {_mmss(r["t"])} '
                        f'= {_mmss(r["adj"])} adjusted'
                        + (" [OUT OF LINE with their other races]" if i in off else "")
                        for i, r in enumerate(p["results"]))
        spread = ""
        if len(p["results"]) == 2:
            a, b = (r["adj"] for r in p["results"])
            if abs(a - b) / min(a, b) > OFF_DAY:
                spread = " Their two races differ by more than 8%, so one may be an off day."
        lines.append(f'- id {p["aid"]}, {p["name"]}: average adjusted {_mmss(p["rating"])} over '
                     f'{p["n"]} race(s).{spread} Results: {res}.')
    # Head-to-head race by race, newest first -- a season total like "1-1" hides WHO won
    # the most recent meeting, which is the thing a coach weighs most.
    shared = defaultdict(list)
    for p in zone:
        for r in p["results"]:
            shared[(r["date"] or "", r["meet"], r["race"])].append((r["t"], p["name"]))
    meets = sorted((k for k, v in shared.items() if len(v) >= 2), reverse=True)
    if meets:
        lines.append("Races where these runners met (newest first):")
        for n, k in enumerate(meets):
            order = ", ".join(f"{nm} {_mmss(t)}" for t, nm in sorted(shared[k]))
            lines.append(f'  {k[0]} {k[1]} ({k[2]}){" — most recent" if n == 0 else ""}: '
                         f'finished in this order: {order}')
    else:
        lines.append("None of these runners have raced each other.")
    return "\n".join(lines)


def _resolve_with_llm(school_id, tossups):
    """Let the model settle the close calls. Returns a note if it could not."""
    prompt = "\n\n".join(_evidence(c) for c in tossups)
    key = (school_id, hash(prompt))
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        data = hit[1]
    else:
        from . import ai
        import anthropic
        try:
            # Adaptive thinking: weighing times, dates and head-to-heads is exactly the
            # reasoning that goes wrong without it -- the first live run, thinking off,
            # wrote a reason that contradicted its own numbers.
            msg = ai._client().messages.create(
                model=ai.CLAUDE_MODEL, max_tokens=16000, system=_SYS,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": _SCHEMA}})
        except (anthropic.APIConnectionError, anthropic.RateLimitError,
                anthropic.APIStatusError, RuntimeError) as e:
            return f"The AI reviewer was unavailable ({type(e).__name__}); close calls use head-to-head."
        if msg.stop_reason != "end_turn":
            return f"The AI reviewer stopped early ({msg.stop_reason}); close calls use head-to-head."
        try:
            data = json.loads(next(b.text for b in msg.content if b.type == "text"))
        except (StopIteration, ValueError):
            return "The AI reviewer's answer could not be read; close calls use head-to-head."
        _CACHE[key] = (time.time(), data)

    by_label = {g.get("group"): g for g in data.get("groups", [])}
    skipped = []
    for cat in tossups:
        tu = cat["tossup"]
        g = by_label.get(cat["label"])
        zone = {p["aid"]: p for p in tu["zone"]}
        ids = [i for i in (g or {}).get("chosen_ids", []) if i in zone]
        # Trust it only when it followed the rules: the right count, only zone runners,
        # no repeats. Otherwise keep the head-to-head order rather than guess.
        if g and len(ids) == tu["slots"] and len(set(ids)) == len(ids):
            tu["chosen"] = [zone[i] for i in ids]
            tu["by"] = "AI review"
            tu["reason"] = g.get("reason", "")
        else:
            skipped.append(cat["label"])
    if skipped:
        return "AI answer didn't fit for " + ", ".join(skipped) + "; those use head-to-head."
    return None
