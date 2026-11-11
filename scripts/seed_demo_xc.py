#!/usr/bin/env python3
"""Create a demo cross country meet in the Demo District, caught between its two races.

    python scripts/seed_demo_xc.py /path/to/xctimer.db [--date YYYY-MM-DD] [--reset]

"Maple Valley XC Invitational": the three demo middle schools, a Girls race and a Boys race.
Bibs are assigned and locked, so stickers and bib lists print with names. The Girls race is
finished and locked (results and team scores have something to show); the Boys race has not
started, so you can start the clock, tap finishers and scan or pick bibs live.

Run scripts/seed_demo_rosters.py first. The meet is built through the app's own routes (the
same requests the browser and the timing phone make). The one thing written directly is the
Girls race's clock: the app only accepts finish times within seconds of "now", so the taps
are recorded live and then spread back over a realistic race.

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

MARK = "xc-v1"                          # meets.settings_json["demo_seed"] — how --reset finds it
NAME = "Maple Valley XC Invitational"
HOST = "Maple Valley Middle School"
SCHOOLS = ["Cedar Ridge Middle School", "Maple Valley Middle School", "Summit View Middle School"]
DONE, WAITING = "Girls", "Boys"
PACE = (920, 80)                        # girls, about 3K: mean and spread in seconds


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
    from xctimerpkg import app as appmod, auth, db

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
    d = q("SELECT id FROM districts WHERE slug='demo'")
    if not d:
        sys.exit("No Demo District (slug 'demo') in this database.")
    did = d[0]["id"]
    sid = {r["name"]: r["id"] for r in q("SELECT id, name FROM schools WHERE district_id=?", did)}
    if any(s not in sid for s in SCHOOLS):
        sys.exit("Demo middle schools are missing — run scripts/seed_demo_rosters.py first.")
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
            raise SystemExit(f"POST {url} -> {r.status_code} {r.get_data(as_text=True)[:200]}")
        return r

    try:
        for mid in old:
            post(f"/meets/{mid}/delete")
            print(f"Removed the previous demo meet ({mid}).")
        build(args, sid, q, run, post)
    finally:
        run("DELETE FROM sessions WHERE token=?", token)


def build(args, sid, q, run, post):
    rng = random.Random(2026)

    # 1. the meet: the app adds the Boys and Girls races and numbers every XC athlete
    r = post("/meets", data={"name": NAME, "sport": "xc", "date": args.date,
                             "host_school_id": str(sid[HOST]), "school_ids": [str(sid[s]) for s in SCHOOLS]})
    mid = int(r.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    post(f"/meets/{mid}/lock-bibs", data={"lock": "1"})        # frozen numbers -> printing is on
    races = {r["name"]: r["id"] for r in q("SELECT id, name FROM races WHERE meet_id=?", mid)}
    if DONE not in races or WAITING not in races:
        raise SystemExit(f"Expected Boys and Girls races, found {sorted(races)}")

    # 2. the Girls race: gun, one tap per finisher, then each bib in finishing order
    girls = q("SELECT mb.bib, a.grade FROM meet_bibs mb JOIN athletes a ON a.id=mb.athlete_id "
              "WHERE mb.meet_id=? AND a.gender='F' ORDER BY mb.bib", mid)
    mean, sd = PACE
    field, used = [], set()
    for g in girls:                                           # 8th graders run a little ahead
        t = round(mean + sd * max(-2.0, min(2.4, rng.gauss(0, 0.9) - (g["grade"] - 7.5) * 0.5)), 1)
        while t in used:
            t = round(t + 0.1, 1)
        used.add(t)
        field.append((t, g["bib"]))
    field.sort()
    rid = races[DONE]
    post(f"/races/{rid}/start", ok=(200,), json={})
    for _ in field:
        post(f"/races/{rid}/tap", ok=(200,), json={})
    for _, bib in field:
        post(f"/races/{rid}/finish", ok=(200,), json={"bib": bib})
    post(f"/races/{rid}/stop", ok=(200,), json={})
    post(f"/races/{rid}/lock", ok=(200,), json={})

    # 3. spread those taps back over a real race (see the module note)
    stop = datetime.datetime.fromisoformat(q("SELECT stop_time FROM races WHERE id=?", rid)[0][0])
    gun = stop - datetime.timedelta(seconds=field[-1][0] + 45)
    run("UPDATE races SET start_time=? WHERE id=?", gun.isoformat(), rid)
    for f, (t, _) in zip(q("SELECT id FROM finishers WHERE race_id=? ORDER BY seq", rid), field):
        run("UPDATE finishers SET elapsed_seconds=?, finish_time=? WHERE id=?",
            t, (gun + datetime.timedelta(seconds=t)).isoformat(), f["id"])

    row = q("SELECT settings_json FROM meets WHERE id=?", mid)[0]
    settings = json.loads(row["settings_json"] or "{}")
    settings["demo_seed"] = MARK
    run("UPDATE meets SET settings_json=? WHERE id=?", json.dumps(settings), mid)
    n_bib = q("SELECT COUNT(*) FROM meet_bibs WHERE meet_id=?", mid)[0][0]
    named = q("SELECT COUNT(*) FROM finishers WHERE race_id=? AND snap_name IS NOT NULL", rid)[0][0]
    print(f"Created '{NAME}' on {args.date}: /meets/{mid}")
    print(f"  {len(SCHOOLS)} schools, {n_bib} runners with bibs (locked for printing)")
    print(f"  {DONE} race finished and locked: {named} finishers, "
          f"{int(field[0][0] // 60)}:{field[0][0] % 60:04.1f} to {int(field[-1][0] // 60)}:{field[-1][0] % 60:04.1f}")
    print(f"  {WAITING} race not started: {n_bib - len(field)} runners ready to time")


if __name__ == "__main__":
    main()
