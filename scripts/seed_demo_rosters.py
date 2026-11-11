#!/usr/bin/env python3
"""Fill the Demo District with schools and rosters for a live demo.

    python scripts/seed_demo_rosters.py /path/to/xctimer.db

Three high schools (grades 9-12) and the three middle schools that feed them (grades 7-8),
216 fictional athletes, and the district grade list set to 7-12 so the high-school events show.
Names are generated from generic first/last name lists and belong to no real person. No
contact details, birth dates or other personal fields are written.

Safe to re-run: it does nothing if the Demo District already has schools. It never touches
another district, and creates no meets and no user accounts.
"""
import json
import random
import sqlite3
import sys

SLUG = "demo"
STEMS = ["Cedar Ridge", "Maple Valley", "Summit View"]
HS_PER, MS_PER = 5, 8          # athletes per grade x gender
GRADES = [7, 8, 9, 10, 11, 12]

BOYS = ["Aiden", "Asher", "Beckett", "Bennett", "Caleb", "Carter", "Cole", "Declan", "Dylan", "Eli",
        "Emmett", "Ethan", "Finn", "Gavin", "Grant", "Henry", "Hudson", "Isaac", "Jace", "Jonah",
        "Kai", "Landon", "Levi", "Liam", "Lucas", "Mason", "Micah", "Miles", "Nolan", "Owen",
        "Parker", "Reid", "Rowan", "Sawyer", "Silas", "Tate", "Theo", "Tucker", "Wyatt", "Zane"]
GIRLS = ["Addison", "Alice", "Aria", "Aubrey", "Ava", "Brielle", "Brooke", "Callie", "Camila", "Claire",
         "Daisy", "Eliza", "Ella", "Emery", "Faith", "Hadley", "Hazel", "Ivy", "Jade", "Josie",
         "Kate", "Kinsley", "Layla", "Lena", "Lucy", "Maya", "Mila", "Naomi", "Nora", "Olive",
         "Paige", "Piper", "Quinn", "Reese", "Ruby", "Sadie", "Sloane", "Tessa", "Violet", "Willa"]
LAST = ["Abbott", "Barlow", "Bishop", "Calloway", "Carver", "Chandler", "Dalton", "Drummond", "Easton",
        "Ellery", "Fairbanks", "Farrow", "Gallagher", "Garrison", "Hadley", "Hale", "Holloway", "Ingram",
        "Jarvis", "Keating", "Kendrick", "Langley", "Lowell", "Mercer", "Merritt", "Nakamura", "Navarro",
        "Okafor", "Ortega", "Pemberton", "Prescott", "Quimby", "Ramsey", "Redmond", "Sandoval", "Sheridan",
        "Tanaka", "Thackeray", "Underhill", "Valdez", "Vance", "Whitaker", "Winslow", "Yates", "Zeller"]


def main(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    d = conn.execute("SELECT * FROM districts WHERE slug=?", (SLUG,)).fetchone()
    if not d:
        sys.exit("No Demo District (slug 'demo') in this database.")
    did = d["id"]
    if conn.execute("SELECT 1 FROM schools WHERE district_id=?", (did,)).fetchone():
        print("Demo District already has schools; nothing changed.")
        return
    rng = random.Random(2026)
    used = set()

    def name(pool):
        while True:
            n = f"{rng.choice(pool)} {rng.choice(LAST)}"
            if n not in used:
                used.add(n)
                return n

    total = 0
    for stem in STEMS:
        for label, grades, per in (("High School", (9, 10, 11, 12), HS_PER), ("Middle School", (7, 8), MS_PER)):
            sid = conn.execute("INSERT INTO schools (district_id, name) VALUES (?,?)",
                               (did, f"{stem} {label}")).lastrowid
            n = 0
            for grade in grades:
                for gender, pool in (("M", BOYS), ("F", GIRLS)):
                    for _ in range(per):
                        # Everyone is out for track; about 3 in 5 also run cross country.
                        conn.execute(
                            "INSERT INTO athletes (school_id, name, grade, gender, does_track, does_xc, active) "
                            "VALUES (?,?,?,?,1,?,1)", (sid, name(pool), grade, gender, 1 if n % 5 < 3 else 0))
                        n += 1
            total += n
            print(f"  {stem} {label}: {n} athletes")
    settings = json.loads(d["settings_json"] or "{}")
    settings["grades"] = GRADES
    conn.execute("UPDATE districts SET settings_json=? WHERE id=?", (json.dumps(settings), did))
    conn.commit()
    conn.close()
    print(f"Added {len(STEMS) * 2} schools and {total} athletes to {d['name']}; grades set to 7-12.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
