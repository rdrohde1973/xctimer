"""Seed a self-contained 'Demo District' for showcasing (handoff §10 Phase 6).

Creates a district, 3 schools with rosters, and a finished XC meet with results
so team scoring + public results + progress cards all have data. Idempotent:
does nothing if the demo district already exists.

CLI:  python -m xctimer.demo_seed
"""
import json
import secrets

from . import db, auth

SLUG = "demo"
DEMO_EMAIL = "demo@xctimer.local"
DEMO_PASSWORD = "Demo1234!"

SCHOOLS = [("Northgate HS", 100, 199), ("Southridge HS", 200, 299), ("Westfield HS", 300, 399)]
FIRST_M = ["Liam", "Noah", "Ethan", "Mason", "Caleb", "Owen", "Aiden", "Luke"]
FIRST_F = ["Ava", "Mia", "Ella", "Nora", "Ruby", "Iris", "Lena", "Cora"]


def _place(conn, meid, unit):
    rows = conn.execute(
        "SELECT r.id, r.mark_seconds, r.mark_metric FROM results r JOIN entries e ON e.id=r.entry_id "
        "WHERE e.meet_event_id=?", (meid,)).fetchall()
    def val(r):
        return r["mark_seconds"] if unit == "seconds" else r["mark_metric"]
    scored = [r for r in rows if val(r) is not None]
    scored.sort(key=lambda r: val(r), reverse=(unit != "seconds"))
    for i, r in enumerate(scored):
        conn.execute("UPDATE results SET place=? WHERE id=?", (i + 1, r["id"]))


def _seed_track_meet(conn, did):
    """A finished demo track meet with events, entries, relays and results."""
    if conn.execute("SELECT 1 FROM meets WHERE district_id=? AND name=?",
                    (did, "Demo Track Classic")).fetchone():
        return False
    schools = conn.execute("SELECT id, name FROM schools WHERE district_id=? ORDER BY id", (did,)).fetchall()
    if not schools:
        return False
    pt = conn.execute("SELECT id FROM points_tables WHERE name='Invitational 10-8-6-4-2-1'").fetchone()
    mid = conn.execute(
        "INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token, points_table_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (did, "track", "Demo Track Classic", "2026-05-15", schools[0]["id"],
         secrets.token_urlsafe(8), pt[0] if pt else None)).lastrowid
    for s in schools:
        conn.execute("INSERT INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, s["id"]))
    ev = {r["name"]: r for r in conn.execute("SELECT id, name, unit, kind FROM events")}
    indiv = [("100m", 12.0, 13.0, 0.18), ("400m", 55.0, 62.0, 0.9), ("1600m", 280.0, 320.0, 3.0)]

    for gender in ("M", "F"):
        for ename, bb, gb, step in indiv:
            e = ev.get(ename)
            if not e:
                continue
            meid = conn.execute("INSERT INTO meet_events (meet_id, event_id, gender, grade) "
                                "VALUES (?,?,?,?)", (mid, e["id"], gender, "")).lastrowid
            base, idx = (bb if gender == "M" else gb), 0
            for s in schools:
                for a in conn.execute("SELECT id, bib, name FROM athletes WHERE school_id=? "
                                      "AND gender=? ORDER BY id LIMIT 3", (s["id"], gender)).fetchall():
                    eid = conn.execute("INSERT INTO entries (meet_event_id, runner_id, school_id) "
                                       "VALUES (?,?,?)", (meid, a["id"], s["id"])).lastrowid
                    conn.execute("INSERT INTO results (entry_id, mark_seconds, dq, snap_name, snap_bib, "
                                 "snap_school) VALUES (?,?,0,?,?,?)",
                                 (eid, round(base + idx * step, 2), a["name"], a["bib"], s["name"]))
                    idx += 1
            _place(conn, meid, "seconds")
        # Long Jump (field)
        e = ev.get("Long Jump")
        if e:
            meid = conn.execute("INSERT INTO meet_events (meet_id, event_id, gender, grade) "
                                "VALUES (?,?,?,?)", (mid, e["id"], gender, "")).lastrowid
            top, idx = (5.4 if gender == "M" else 4.8), 0
            for s in schools:
                for a in conn.execute("SELECT id, bib, name FROM athletes WHERE school_id=? "
                                      "AND gender=? ORDER BY id LIMIT 2", (s["id"], gender)).fetchall():
                    eid = conn.execute("INSERT INTO entries (meet_event_id, runner_id, school_id) "
                                       "VALUES (?,?,?)", (meid, a["id"], s["id"])).lastrowid
                    conn.execute("INSERT INTO results (entry_id, mark_metric, dq, snap_name, snap_bib, "
                                 "snap_school) VALUES (?,?,0,?,?,?)",
                                 (eid, round(top - idx * 0.12, 2), a["name"], a["bib"], s["name"]))
                    idx += 1
            _place(conn, meid, "metric")
        # 4x100m Relay
        e = ev.get("4x100m Relay")
        if e:
            meid = conn.execute("INSERT INTO meet_events (meet_id, event_id, gender, grade) "
                                "VALUES (?,?,?,?)", (mid, e["id"], gender, "")).lastrowid
            base = 48.0 if gender == "M" else 52.0
            for i, s in enumerate(schools):
                members = [r["name"] for r in conn.execute(
                    "SELECT name FROM athletes WHERE school_id=? AND gender=? ORDER BY id LIMIT 4",
                    (s["id"], gender)).fetchall()]
                eid = conn.execute("INSERT INTO entries (meet_event_id, school_id, relay_label, members_json) "
                                   "VALUES (?,?,?,?)", (meid, s["id"], "A", json.dumps(members))).lastrowid
                conn.execute("INSERT INTO results (entry_id, mark_seconds, dq, snap_name, snap_bib, snap_school) "
                             "VALUES (?,?,0,?,?,?)", (eid, round(base + i * 0.6, 2),
                                                      f"{s['name']} A", None, s["name"]))
            _place(conn, meid, "seconds")
    return True


def seed():
    conn = db.connect()
    row = conn.execute("SELECT id FROM districts WHERE slug=?", (SLUG,)).fetchone()
    if row:
        did = row[0]
        track = _seed_track_meet(conn, did)
        conn.commit()
        conn.close()
        return {"created": False, "note": "Demo District already existed",
                "track_meet_added": track}

    did = conn.execute("INSERT INTO districts (name, slug) VALUES (?,?)",
                       ("Demo District", SLUG)).lastrowid

    school_ids = []
    athletes = {"M": [], "F": []}   # (athlete_id, bib, name, grade, gender, school_name)
    for name, lo, hi in SCHOOLS:
        sid = conn.execute(
            "INSERT INTO schools (district_id, name, bib_start, bib_end) VALUES (?,?,?,?)",
            (did, name, lo, hi)).lastrowid
        school_ids.append(sid)
        bib = lo
        for i in range(5):  # 5 boys
            nm = f"{FIRST_M[i]} {name.split()[0][:4]}"
            aid = conn.execute("INSERT INTO athletes (school_id, bib, name, grade, gender) "
                               "VALUES (?,?,?,?,?)", (sid, bib, nm, 9 + (i % 4), "M")).lastrowid
            athletes["M"].append((aid, bib, nm, 9 + (i % 4), "M", name)); bib += 1
        for i in range(5):  # 5 girls
            nm = f"{FIRST_F[i]} {name.split()[0][:4]}"
            aid = conn.execute("INSERT INTO athletes (school_id, bib, name, grade, gender) "
                               "VALUES (?,?,?,?,?)", (sid, bib, nm, 9 + (i % 4), "F")).lastrowid
            athletes["F"].append((aid, bib, nm, 9 + (i % 4), "F", name)); bib += 1

    # Finished XC meet
    mid = conn.execute(
        "INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token) "
        "VALUES (?,?,?,?,?,?)",
        (did, "xc", "Demo XC Invitational", "2026-09-19", school_ids[0],
         secrets.token_urlsafe(8))).lastrowid
    for sid in school_ids:
        conn.execute("INSERT INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, sid))
    rid = conn.execute("INSERT INTO races (meet_id, name, capture_mode, start_time, stop_time) "
                       "VALUES (?,?,?,?,?)",
                       (mid, "Varsity", "tap", "2026-09-19T09:00:00+00:00",
                        "2026-09-19T09:30:00+00:00")).lastrowid

    def add_finishers(group, base):
        # Interleave schools so team scores differ; times increase by rank.
        ordered = sorted(group, key=lambda a: (group.index(a) % 5, group.index(a)))
        seq = conn.execute("SELECT COALESCE(MAX(seq),0) FROM finishers WHERE race_id=?",
                           (rid,)).fetchone()[0]
        for i, (aid, bib, nm, grade, gender, school) in enumerate(ordered):
            seq += 1
            elapsed = base + i * 7.3
            conn.execute(
                "INSERT INTO finishers (race_id, seq, bib, elapsed_seconds, dq, "
                "snap_name, snap_grade, snap_gender, snap_school) VALUES (?,?,?,?,?,?,?,?,?)",
                (rid, seq, bib, elapsed, 0, nm, grade, gender, school))

    add_finishers(athletes["M"], 1020.0)   # ~17:00 boys
    add_finishers(athletes["F"], 1200.0)   # ~20:00 girls

    # Read-only demo coach (scoped to the first school), password set directly.
    uid = conn.execute(
        "INSERT INTO users (district_id, email, name, role, password_hash, is_demo) "
        "VALUES (?,?,?,?,?,1)",
        (did, DEMO_EMAIL, "Demo Coach", "coach", auth.hash_password(DEMO_PASSWORD))).lastrowid
    conn.execute("INSERT INTO user_schools (user_id, school_id) VALUES (?,?)", (uid, school_ids[0]))

    _seed_track_meet(conn, did)   # also give the demo a finished track meet

    conn.commit()
    conn.close()
    return {"created": True, "district_id": did, "schools": len(school_ids),
            "athletes": len(athletes["M"]) + len(athletes["F"]),
            "demo_login": (DEMO_EMAIL, DEMO_PASSWORD)}


if __name__ == "__main__":
    r = seed()
    print(r)
