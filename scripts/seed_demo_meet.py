#!/usr/bin/env python3
"""Create a demo track meet in the Demo District, caught mid-meet for a live demo.

    python scripts/seed_demo_meet.py /path/to/xctimer.db [--date YYYY-MM-DD] [--reset]

"Cedar Ridge Invitational": the three demo high schools, Boys and Girls, 18 event types.
Entries are in, bibs are assigned and every running event has seeded heats and lanes. The
first half of the meet is already scored (so Results and team scores have something to
show); the second half is drawn and waiting, so you can time a heat or enter a field mark
live. What is left open:

    running   400m, 300m Hurdles, 800m, 200m, 3200m, 4x400m Relay
    field     Triple Jump (both), Boys Pole Vault, Boys Discus

Run scripts/seed_demo_rosters.py first. Everything goes through the app's own routes (the
same requests the browser makes), so the meet is exactly what a coach would have built by
hand. Athletes are the fictional demo roster; marks are random but plausible.

Re-running does nothing if the demo meet exists. --reset deletes it and builds a fresh one,
which is how to put it back after a demo. Nothing outside the Demo District is touched.
"""
import argparse
import datetime
import json
import os
import random
import sys
import tempfile

MARK = "track-v1"                       # meets.settings_json["demo_seed"] — how --reset finds it
NAME = "Cedar Ridge Invitational"
HOST = "Cedar Ridge High School"
SCHOOLS = ["Cedar Ridge High School", "Maple Valley High School", "Summit View High School"]
POINTS = "Invitational 10-8-6-5-4-3-2-1"

# Meet-day order of the running events (field events run alongside).
ORDER = ["4x800m Relay", "100m Hurdles", "110m Hurdles", "100m", "1600m", "4x100m Relay",
         "400m", "300m Hurdles", "800m", "200m", "3200m", "4x400m Relay"]
DONE_RUNNING = set(ORDER[:6])
DONE_FIELD = {("Long Jump", "M"), ("Long Jump", "F"), ("High Jump", "M"), ("High Jump", "F"),
              ("Shot Put", "M"), ("Shot Put", "F"), ("Pole Vault", "F"), ("Discus", "F")}

# Who enters what, by slot in a school's 20-athlete boys or girls squad:
# 0-6 sprinters, 7-11 distance, 12-15 hurdles/jumps, 16-19 throws. Nobody exceeds 4 individual events.
S, D, J, T = range(0, 7), range(7, 12), range(12, 16), range(16, 20)
SLOTS = {
    "100m": [S[0], S[1], S[2], S[3]], "200m": [S[0], S[1], S[4], S[5]],
    "400m": [S[4], S[5], S[6], D[0]], "800m": [D[0], D[1], D[2]],
    "1600m": [D[1], D[3], D[4]], "3200m": [D[2], D[3], D[4]],
    "HURDLES": [J[0], J[1], J[2], J[3]], "300m Hurdles": [J[0], J[1], J[2], J[3]],
    "4x100m Relay": [S[0], S[1], S[2], S[3]], "4x400m Relay": [S[4], S[5], S[6], D[0]],
    "4x800m Relay": [D[0], D[1], D[2], D[3]],
    "Long Jump": [S[2], S[3], J[2]], "Triple Jump": [S[6], J[0], J[2]],
    "High Jump": [J[1], J[3], S[3]], "Pole Vault": [J[1], S[6]],
    "Shot Put": [T[0], T[1], T[2]], "Discus": [T[0], T[1], T[3]],
}
# (mean, spread) — seconds for running, inches for field — Boys then Girls.
NORMS = {
    "100m": ((11.9, 0.45), (13.5, 0.5)), "200m": ((24.3, 0.9), (27.8, 1.0)),
    "400m": ((54.5, 2.2), (63.5, 2.8)), "800m": ((128, 6), (152, 8)),
    "1600m": ((292, 14), (348, 18)), "3200m": ((640, 30), (765, 40)),
    "110m Hurdles": ((17.2, 1.0), None), "100m Hurdles": (None, (17.6, 1.1)),
    "300m Hurdles": ((44.5, 2.2), (51.5, 2.6)),
    "4x100m Relay": ((45.6, 0.9), (51.8, 1.0)), "4x400m Relay": ((218, 5), (258, 6)),
    "4x800m Relay": ((515, 12), (615, 15)),
    "Long Jump": ((228, 14), (186, 12)), "Triple Jump": ((470, 22), (394, 20)),
    "Shot Put": ((486, 48), (366, 40)), "Discus": ((1380, 160), (1080, 130)),
    "High Jump": ((68, 3), (57, 3)), "Pole Vault": ((132, 12), (96, 10)),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db")
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()
    datetime.date.fromisoformat(args.date)
    if not os.path.exists(args.db):
        sys.exit(f"No database at {args.db}")

    # The repo directory is the package; give it an importable name without assuming what
    # the checkout is called, and point it at the requested database before it loads.
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp = tempfile.mkdtemp()
    os.symlink(root, os.path.join(tmp, "xctimerpkg"))
    sys.path.insert(0, tmp)
    os.environ["XCTIMER_DB"] = os.path.abspath(args.db)
    os.environ.setdefault("XC_MAIL_DISABLE", "1")
    from xctimerpkg import app as appmod, auth, db, track

    def q(sql, *a):
        c = db.connect()
        try:
            return c.execute(sql, a).fetchall()
        finally:
            c.close()

    def run(sql, *a):
        c = db.connect()
        try:
            c.execute(sql, a)
            c.commit()
        finally:
            c.close()

    application = appmod.create_app()
    d = q("SELECT id, name FROM districts WHERE slug='demo'")
    if not d:
        sys.exit("No Demo District (slug 'demo') in this database.")
    did = d[0]["id"]
    sid = {r["name"]: r["id"] for r in q("SELECT id, name FROM schools WHERE district_id=?", did)}
    if any(s not in sid for s in SCHOOLS):
        sys.exit("Demo high schools are missing — run scripts/seed_demo_rosters.py first.")
    old = [r["id"] for r in q("SELECT id, settings_json FROM meets WHERE district_id=?", did)
           if json.loads(r["settings_json"] or "{}").get("demo_seed") == MARK]
    if old and not args.reset:
        print(f"Demo meet already exists (/meets/{old[0]}); use --reset to rebuild it.")
        return
    su = q("SELECT id FROM users WHERE role='super_admin' ORDER BY id LIMIT 1")
    if not su:
        sys.exit("No super admin account to act as.")

    token = auth.create_session(su[0]["id"])
    web = application.test_client()
    web.set_cookie(auth.SESSION_COOKIE, token)
    web.set_cookie("csrftoken", "x")
    with web.session_transaction() as s:
        s["active_district_id"] = did
    H = {"X-CSRF-Token": "x"}

    def post(url, ok=(302,), **kw):
        r = web.post(url, headers=H, **kw)
        if r.status_code not in ok:
            raise SystemExit(f"POST {url} -> {r.status_code}")
        return r

    try:
        for mid in old:
            post(f"/meets/{mid}/delete")
            print(f"Removed the previous demo meet ({mid}).")
        build(args, did, sid, q, run, post, track)
    finally:
        run("DELETE FROM sessions WHERE token=?", token)


def build(args, did, sid, q, run, post, track):
    rng = random.Random(2026)
    ids = [sid[s] for s in SCHOOLS]

    # 1. the meet, its events, and the setup form
    r = post("/meets", data={"name": NAME, "sport": "track", "date": args.date,
                             "host_school_id": str(sid[HOST]), "school_ids": [str(i) for i in ids]})
    mid = int(r.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    ev = {r["name"]: r for r in q("SELECT * FROM events")}
    both = [n for n in NORMS if "Hurdles" not in n or n == "300m Hurdles"]
    post(f"/meets/{mid}/events", data={"event_ids": [str(ev[n]["id"]) for n in both], "genders": ["M", "F"]})
    post(f"/meets/{mid}/events", data={"event_ids": [str(ev["110m Hurdles"]["id"])], "genders": ["M"]})
    post(f"/meets/{mid}/events", data={"event_ids": [str(ev["100m Hurdles"]["id"])], "genders": ["F"]})
    pt = q("SELECT id FROM points_tables WHERE name=?", POINTS)
    post(f"/meets/{mid}/track-setup", data={
        "school_ids": [str(i) for i in ids], "host_school_id": str(sid[HOST]),
        "points_table_id": str(pt[0]["id"]) if pt else "", "event_limit": "4", "lanes": "8",
        "hj_low": "4-00", "hj_high": "6-04", "hj_inc": "2",
        "pv_low": "6-00", "pv_high": "13-00", "pv_inc": "6"})
    post(f"/meets/{mid}/events/type-order", ok=(200,), json={"order": ORDER})
    me = {(r["ename"], r["gender"]): r for r in q(
        "SELECT me.*, e.name AS ename, e.kind, e.unit FROM meet_events me JOIN events e ON e.id=me.event_id "
        "WHERE me.meet_id=?", mid)}

    # 2. each coach's entries (one "Assign athletes" save per school), and how good everyone is
    ability, squad = {}, {}
    for school in SCHOOLS:
        form = {}
        for gender in ("M", "F"):
            roster = list(q("SELECT id, name, grade FROM athletes WHERE school_id=? AND gender=? AND active=1 "
                            "AND does_track=1 ORDER BY id", sid[school], gender))
            if len(roster) < 20:
                raise SystemExit(f"{school} has only {len(roster)} {gender} athletes; expected 20.")
            rng.shuffle(roster)
            squad[(school, gender)] = roster
            for a in roster:      # lower = better; upperclassmen run a little ahead
                ability[a["id"]] = rng.gauss(0, 0.8) - (a["grade"] - 10.5) * 0.25
            for key, slots in SLOTS.items():
                name = ("110m Hurdles" if gender == "M" else "100m Hurdles") if key == "HURDLES" else key
                for i in slots:
                    form.setdefault(f"me_{roster[i]['id']}", []).append(str(me[(name, gender)]["id"]))
        post(f"/meets/{mid}/assign?school={sid[school]}", data=form)

    # 3. true marks, and season-best seeds for the running events so heats draw fastest-last
    entries = q("SELECT en.*, e.name AS ename, e.unit, me.gender FROM entries en "
                "JOIN meet_events me ON me.id=en.meet_event_id JOIN events e ON e.id=me.event_id "
                "WHERE me.meet_id=?", mid)
    by_name = {a["name"]: a["id"] for roster in squad.values() for a in roster}
    true = {}
    for e in entries:
        mean, sd = NORMS[e["ename"]][0 if e["gender"] == "M" else 1]
        if e["runner_id"]:
            z = ability[e["runner_id"]]
        else:
            legs = [ability[by_name[n]] for n in json.loads(e["members_json"] or "[]")]
            z = sum(legs) / max(1, len(legs))
        z = max(-2.2, min(2.2, z + rng.gauss(0, 0.35)))
        true[e["id"]] = mean + sd * z if e["unit"] == "seconds" else mean - sd * z
        if e["unit"] == "seconds":
            run("UPDATE entries SET seed=? WHERE id=?", round(true[e["id"]] * (1 + rng.gauss(0, 0.01)), 2), e["id"])
    post(f"/meets/{mid}/draw-all", data={"mode": "seeded"})

    # 4. score the first half of the meet
    done = 0
    for (name, gender), m_ev in sorted(me.items(), key=lambda kv: kv[1]["id"]):
        mine = [e for e in entries if e["meet_event_id"] == m_ev["id"]]
        if m_ev["unit"] == "seconds":
            if name not in DONE_RUNNING:
                continue
            form, used = {}, set()
            for e in mine:
                t = round(true[e["id"]] * (1 + rng.gauss(0, 0.01)), 2)
                while t in used:              # no dead heats: a tie is a distraction in a demo
                    t = round(t + 0.01, 2)
                used.add(t)
                form[f"mark_{e['id']}"] = track.fmt_time(t)
            post(f"/meet-events/{m_ev['id']}/marks", data=form)
        elif (name, gender) not in DONE_FIELD:
            continue
        elif name in ("High Jump", "Pole Vault"):
            bars = json.loads(m_ev["bar_heights"] or "[]")
            hts = [track._parse_ht(b) for b in bars]
            rows, taken = [], {}
            for e in sorted(mine, key=lambda e: -true[e["id"]]):
                top = max([i for i, h in enumerate(hts) if h <= true[e["id"]]] or [0])
                top = min(top, len(bars) - 2)
                # A clear 1-2-3, then at most two jumpers sharing any lower height.
                share = 1 if len(rows) < 3 else 2
                if len(rows) >= 3:            # never level with a medalist
                    top = min(top, max(0, min(taken) - (1 if len(rows) == 3 else 0)))
                while taken.get(top, 0) >= share and top > 0:
                    top -= 1
                taken[top] = taken.get(top, 0) + 1
                first = max(0, top - rng.choice((2, 3, 4)))
                marks = {bars[i]: rng.choices(("O", "XO", "XXO"), (60, 25, 15))[0] for i in range(first, top + 1)}
                marks[bars[top + 1]] = "XXX"
                rows.append({"eid": e["id"], "marks": marks})
            post(f"/meet-events/{m_ev['id']}/hj-save", ok=(200,), json={"bars": bars, "rows": rows})
        else:
            step, gap = (1.0, 40.0) if name == "Discus" else (0.25, 14.0 if name == "Shot Put" else 9.0)
            form = {}
            for e in mine:
                best = round(true[e["id"]] / step) * step
                tries = [best] + [best - round(rng.uniform(2, gap) / step) * step for _ in range(2)]
                rng.shuffle(tries)
                for n, v in enumerate(tries, 1):
                    foul = v != best and rng.random() < 0.2
                    form[f"a{n}_{e['id']}"] = "F" if foul else track._fmt_ht(v)
            post(f"/meet-events/{m_ev['id']}/marks", data=form)
        done += 1

    row = q("SELECT settings_json, public_token FROM meets WHERE id=?", mid)[0]
    settings = json.loads(row["settings_json"] or "{}")
    settings["demo_seed"] = MARK
    run("UPDATE meets SET settings_json=? WHERE id=?", json.dumps(settings), mid)
    n_res = q("SELECT COUNT(*) FROM results r JOIN entries en ON en.id=r.entry_id JOIN meet_events me "
              "ON me.id=en.meet_event_id WHERE me.meet_id=? AND r.place IS NOT NULL", mid)[0][0]
    n_bib = q("SELECT COUNT(*) FROM meet_bibs WHERE meet_id=?", mid)[0][0]
    print(f"Created '{NAME}' on {args.date}: /meets/{mid}")
    print(f"  {len(SCHOOLS)} schools, {n_bib} athletes with bibs, {len(me)} events, {len(entries)} entries")
    print(f"  {done} events scored ({n_res} placed results), {len(me) - done} drawn and waiting")


if __name__ == "__main__":
    main()
