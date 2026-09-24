"""Championship picks: the 7 fastest per school per grade x gender, fairly compared.

Times from different courses cannot be compared raw -- a hilly course is slower for
everyone. So every XC result in the database feeds one additive model on log-time:

    log(time) = ability[runner] + difficulty[race]

fitted by alternating means. A race's difficulty is learned from the runners who ran
it AND something else, which is why it works: 96 runners linked the five meets of
September 2026, 18-39 shared runners per pair. The fitted ability, turned back into
a time, is "what this runner would run on an average course". The model uses each
RACE, not each meet, so a meet where boys and girls ran different distances is fine.

Races are only compared when they share at least MIN_SHARED runners, directly or
through a chain -- a race nothing ties to the others (a 1-mile time trial for a team
that has not raced yet) would otherwise be centred on its own average and a 1-mile
time would beat real 2-mile runners. Ratings come from REAL races; a time trial's time
only counts for a runner with nothing else, and is flagged. Finishing ORDER in a time
trial is another matter: everyone ran the same distance, so it counts fully as
head-to-head -- coaches run one before a championship precisely to settle close calls.

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
MIN_SHARED = 5         # runners two races must share before their difficulties are compared
_ITER = 200
_CACHE, _CACHE_TTL = {}, 1800   # LLM answers per (school, data fingerprint), 30 min


# ------------------------------------------------------------------ data
def _results(conn):
    """Every timed, non-DQ XC result, resolved to an athlete through meet_bibs."""
    return conn.execute(
        "SELECT mb.athlete_id AS aid, a.name, a.grade, a.gender, a.school_id AS sid, "
        "       ra.id AS rid, ra.name AS race, m.id AS mid, m.name AS meet, m.date, "
        "       COALESCE(m.time_trial,0) AS tt, "
        "       f.elapsed_seconds AS t "
        "FROM meet_bibs mb "
        "JOIN races ra ON ra.meet_id=mb.meet_id "
        "JOIN finishers f ON f.race_id=ra.id AND f.bib=mb.bib "
        "JOIN meets m ON m.id=ra.meet_id "
        "JOIN athletes a ON a.id=mb.athlete_id "
        "WHERE m.sport='xc' AND f.elapsed_seconds > 0 AND COALESCE(f.dq,0)=0").fetchall()


def _groups(rows):
    """Which races can be compared: {race: group}. Two races are linked when at least
    MIN_SHARED runners ran both; a group is everything linked, directly or in a chain.
    A race with too few shared runners is a group of its own and is never compared
    with the others -- its difficulty would rest on one or two runners' say-so."""
    by_r = defaultdict(set)
    for r in rows:
        by_r[r["rid"]].add(r["aid"])
    rids = sorted(by_r)
    nbr = defaultdict(set)
    for i, a in enumerate(rids):
        for b in rids[i + 1:]:
            if len(by_r[a] & by_r[b]) >= MIN_SHARED:
                nbr[a].add(b)
                nbr[b].add(a)
    grp = {}
    for start in rids:
        if start in grp:
            continue
        grp[start] = start
        stack = [start]
        while stack:
            x = stack.pop()
            for y in nbr[x]:
                if y not in grp:
                    grp[y] = start
                    stack.append(y)
    return grp


def fit(rows):
    """Alternating means on log-time, separately inside each group of comparable races.

    Returns (ability{(runner, group)}, difficulty{race}, group{race}). A runner who ran
    in two unlinked groups gets an ability in each, never one averaged across them.
    """
    grp = _groups(rows)
    by_a, by_r = defaultdict(list), defaultdict(list)
    for r in rows:
        k = (r["aid"], grp[r["rid"]])
        lt = math.log(r["t"])
        by_a[k].append((r["rid"], lt))
        by_r[r["rid"]].append((k, lt))
    members = defaultdict(list)
    for rid, g in grp.items():
        members[g].append(rid)
    df, ab = defaultdict(float), {}
    for _ in range(_ITER):
        ab = {k: sum(lt - df[rid] for rid, lt in xs) / len(xs) for k, xs in by_a.items()}
        new = {rid: sum(lt - ab[k] for k, lt in xs) / len(xs) for rid, xs in by_r.items()}
        # Only differences are identified inside a group; pin each group's average race
        # to zero so an ability turns back into a time on that group's typical course.
        df = defaultdict(float)
        for g, ids in members.items():
            mean = sum(new[r] for r in ids) / len(ids)
            for r in ids:
                df[r] = new[r] - mean
    return ab, dict(df), grp


def course_table(rows, df, grp):
    """Per race: slower/faster than the average course FOR THAT GENDER, among the races
    that can be compared. Boys' and girls' races are tied only through a mixed heat, so
    each gender is shown against its own average. A race not linked to the rest shows
    no number -- there is nothing to measure it against."""
    seen, sexes = {}, defaultdict(lambda: defaultdict(int))
    for r in rows:
        seen.setdefault(r["rid"], (r["meet"], r["race"], r["date"], r["tt"]))
        sexes[r["rid"]][r["gender"] or "?"] += 1
    gender = {rid: max(sx, key=sx.get) for rid, sx in sexes.items()}
    size = defaultdict(int)
    for rid in seen:
        size[(gender[rid], grp[rid])] += sum(sexes[rid].values())
    main = {}
    for (gx, g), n in size.items():
        if n > size.get((gx, main.get(gx)), -1):
            main[gx] = g
    base = {}
    for gx, g in main.items():
        ids = [rid for rid in seen if gender[rid] == gx and grp[rid] == g]
        base[gx] = sum(df.get(rid, 0.0) for rid in ids) / len(ids)
    word = {"M": "Boys", "F": "Girls"}
    out = []
    for rid, v in seen.items():
        gx = gender[rid]
        linked = grp[rid] == main.get(gx)
        out.append({"rid": rid, "meet": v[0], "race": v[1], "date": v[2], "tt": bool(v[3]),
                    "group": word.get(gx, "Other"), "linked": linked,
                    "pct": (math.exp(df.get(rid, 0.0) - base[gx]) - 1) * 100 if linked else None})
    return sorted(out, key=lambda x: (x["group"], x["date"] or ""))


def _meetings(rows, ids):
    """Every race two runners both ran: {(a, b): [(date, a_time, b_time), ...]} newest
    first. Time trials count in full: everyone in one race ran the same distance, so
    the finishing order is direct evidence whatever that distance was."""
    by_race, when = defaultdict(dict), {}
    for r in rows:
        if r["aid"] in ids:
            by_race[r["rid"]][r["aid"]] = r["t"]
            when[r["rid"]] = r["date"] or ""
    out = defaultdict(list)
    for rid, times in by_race.items():
        for a in times:
            for b in times:
                if a != b:
                    out[(a, b)].append((when[rid], times[a], times[b]))
    for k in out:
        out[k].sort(reverse=True)
    return out


# ------------------------------------------------------------------ selection
def suggest(school_id, use_llm=True):
    """Suggested picks for one school, every grade x gender. Never writes anything."""
    conn = db.connect()
    rows = _results(conn)
    roster = conn.execute(
        "SELECT id, name, grade, gender, does_champ FROM athletes "
        "WHERE school_id=? AND active=1 AND does_xc=1", (school_id,)).fetchall()
    conn.close()
    ab, df, grp = fit(rows) if rows else ({}, {}, {})
    mine = defaultdict(list)
    for r in rows:
        if r["sid"] == school_id:
            mine[r["aid"]].append(r)

    cats, uncategorised = defaultdict(list), []
    for a in roster:
        if a["grade"] is None or a["gender"] not in ("M", "F"):
            uncategorised.append(dict(a))
            continue
        cats[(a["grade"], a["gender"])].append({
            "aid": a["id"], "name": a["name"], "picked_now": bool(a["does_champ"]),
            "_res": sorted(mine.get(a["id"], []), key=lambda r: r["date"] or "")})

    out, tossups = [], []
    for (gr, gx) in sorted(cats, key=lambda k: (k[0], 0 if k[1] == "F" else 1)):
        people = cats[(gr, gx)]
        # Compare this category on the group of courses most of its runners raced in.
        who = defaultdict(set)
        for p in people:
            for r in p["_res"]:
                who[grp[r["rid"]]].add(p["aid"])
        main = max(who, key=lambda g: len(who[g])) if who else None
        for p in people:
            usable = [r for r in p["_res"] if grp.get(r["rid"]) == main]
            real = [r for r in usable if not r["tt"]]
            # Real races set the rating. A time trial may have been a different distance
            # and run at practice effort, so its TIME counts only for a runner who has
            # nothing else -- and that is flagged.
            use = real or usable
            p["tt_only"] = bool(use) and not real
            p["n"] = len(use)
            p["rating"] = (math.exp(sum(math.log(r["t"]) - df[r["rid"]] for r in use) / len(use))
                           if use else None)
            p["why_unranked"] = (None if use else
                                 "Results can't be compared" if p["_res"] else "No XC result yet")
            p["results"] = [{"meet": r["meet"], "race": r["race"], "date": r["date"], "t": r["t"],
                             "tt": bool(r["tt"]), "used": any(r is u for u in use),
                             "adj": (r["t"] / math.exp(df[r["rid"]])
                                     if grp.get(r["rid"]) == main else None)}
                            for r in p["_res"]]
            del p["_res"]
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
                met = _meetings(rows, {p["aid"] for p in zone})

                def last(a, b):
                    """True/False: did a beat b the most recent time they raced? None: never met."""
                    m = met.get((a["aid"], b["aid"]))
                    return (m[0][1] < m[0][2]) if m else None

                for p in zone:
                    p["h2h"] = {}
                    for q in zone:
                        m = met.get((p["aid"], q["aid"]))
                        if q is not p and m:
                            p["h2h"][q["name"]] = [sum(1 for x in m if x[1] < x[2]),
                                                   sum(1 for x in m if x[1] > x[2])]
                # Deterministic order: most recent head-to-head first -- that is what a
                # pre-championship run-off is for -- then all head-to-head, then rating.
                order = sorted(zone, key=lambda p: (
                    -sum((1 if last(p, q) else -1) for q in zone
                         if q is not p and last(p, q) is not None),
                    -sum(w - l for w, l in p["h2h"].values()),
                    p["rating"]))
                chosen, left = order[:slots], order[slots:]
                # Settled when every pick beat every runner left out the LAST time they
                # raced each other. No judgement needed, so it never goes to the LLM, which
                # only sees real close calls: runners who never met, or whose latest
                # meeting points the other way.
                settled = all(last(a, b) is True for a in chosen for b in left)
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
            "courses": course_table(rows, df, grp), "llm_note": note,
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
    "Results marked [time trial] were practice runs, possibly over a different distance "
    "(a 1-mile trial is not a 2-mile race). Their TIMES are scaled but are weaker "
    "evidence than real races, so the average leaves them out when real races exist. "
    "Their FINISHING ORDER is different: everyone ran the same distance, so it is direct "
    "head-to-head evidence. A time trial run just before a championship is often a "
    "run-off the coach held to settle exactly these close calls; treat who finished "
    "ahead in it as strong evidence.\n\n"
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
    idx = [i for i, r in enumerate(p["results"]) if r.get("used", True) and r["adj"] is not None]
    adj = [p["results"][i]["adj"] for i in idx]
    if len(adj) < 3:
        return set()
    # Median of ALL their races: with three or more, one bad race cannot move it. (The
    # median of the OTHER races, tried first, averages the outlier into the baseline
    # when there are only three, and then flags the good races too.)
    srt = sorted(adj)
    n = len(srt)
    mid = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {idx[k] for k, a in enumerate(adj) if abs(a - mid) / mid > OFF_DAY}


def _evidence(cat):
    tu = cat["tossup"]
    zone = tu["zone"]
    lines = [f'GROUP "{cat["label"]}": choose {tu["slots"]} of these {len(zone)}.']
    for p in zone:
        off = _off_days(p)
        def one(i, r):
            s_ = f'{r["date"]} {r["meet"]} ({r["race"]}): {_mmss(r["t"])}'
            s_ += f' = {_mmss(r["adj"])} adjusted' if r["adj"] is not None else " [course not comparable]"
            if r.get("tt"):
                s_ += " [time trial" + ("" if r.get("used") else ", not in their average") + "]"
            if i in off:
                s_ += " [OUT OF LINE with their other races]"
            return s_
        res = "; ".join(one(i, r) for i, r in enumerate(p["results"]))
        spread = ""
        used = [r["adj"] for r in p["results"] if r.get("used", True) and r["adj"] is not None]
        if len(used) == 2:
            a, b = used
            if abs(a - b) / min(a, b) > OFF_DAY:
                spread = " Their two races differ by more than 8%, so one may be an off day."
        lines.append(f'- id {p["aid"]}, {p["name"]}: average adjusted {_mmss(p["rating"])} over '
                     f'{p["n"]} race(s){" (TIME TRIAL ONLY)" if p.get("tt_only") else ""}.'
                     f'{spread} Results: {res}.')
    # Head-to-head race by race, newest first -- a season total like "1-1" hides WHO won
    # the most recent meeting, which is the thing a coach weighs most.
    shared = defaultdict(list)
    for p in zone:
        for r in p["results"]:
            shared[(r["date"] or "", r["meet"] + (" [time trial]" if r.get("tt") else ""),
                    r["race"])].append((r["t"], p["name"]))
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
