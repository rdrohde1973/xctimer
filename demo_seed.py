"""Seed a self-contained 'Demo District' for showcasing (handoff §10 Phase 6).

Creates a district, 3 schools with rosters, and a finished XC meet with results
so team scoring + public results + progress cards all have data. Idempotent:
does nothing if the demo district already exists.

CLI:  python -m xctimer.demo_seed
"""
import secrets

from . import db, auth

SLUG = "demo"
DEMO_EMAIL = "demo@xctimer.local"
DEMO_PASSWORD = "Demo1234!"

SCHOOLS = [("Northgate HS", 100, 199), ("Southridge HS", 200, 299), ("Westfield HS", 300, 399)]
FIRST_M = ["Liam", "Noah", "Ethan", "Mason", "Caleb", "Owen", "Aiden", "Luke"]
FIRST_F = ["Ava", "Mia", "Ella", "Nora", "Ruby", "Iris", "Lena", "Cora"]


def seed():
    conn = db.connect()
    if conn.execute("SELECT 1 FROM districts WHERE slug=?", (SLUG,)).fetchone():
        conn.close()
        return {"created": False, "note": "Demo District already exists"}

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

    conn.commit()
    conn.close()
    return {"created": True, "district_id": did, "schools": len(school_ids),
            "athletes": len(athletes["M"]) + len(athletes["F"]),
            "demo_login": (DEMO_EMAIL, DEMO_PASSWORD)}


if __name__ == "__main__":
    r = seed()
    print(r)
