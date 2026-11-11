#!/usr/bin/env python3
"""Put the demo school logos on the six Demo District schools.

    python scripts/seed_demo_logos.py /path/to/xctimer.db

Copies scripts/demo_logos/*.png (drawn by scripts/make_demo_logos.py) into static/logos/ as
demo-<school>.png and points each demo school at its logo. Run scripts/seed_demo_rosters.py
first. Safe to re-run. A school whose logo somebody uploaded by hand is left alone, and
nothing outside the Demo District is touched.
"""
import os
import shutil
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "demo_logos")
DEST = os.path.join(os.path.dirname(HERE), "static", "logos")
PREFIX = "/static/logos/demo-"


def main(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    d = conn.execute("SELECT id, name FROM districts WHERE slug='demo'").fetchone()
    if not d:
        sys.exit("No Demo District (slug 'demo') in this database.")
    os.makedirs(DEST, exist_ok=True)
    done = 0
    for s in conn.execute("SELECT id, name, logo_path FROM schools WHERE district_id=? ORDER BY name", (d["id"],)):
        slug = s["name"].lower().replace(" ", "-")
        src = os.path.join(SRC, f"{slug}.png")
        if not os.path.exists(src):
            continue                                    # not one of the six demo schools
        if s["logo_path"] and not s["logo_path"].startswith(PREFIX):
            print(f"  {s['name']}: keeps its uploaded logo")
            continue
        shutil.copyfile(src, os.path.join(DEST, f"demo-{slug}.png"))
        conn.execute("UPDATE schools SET logo_path=? WHERE id=?", (f"{PREFIX}{slug}.png", s["id"]))
        print(f"  {s['name']}: {PREFIX}{slug}.png")
        done += 1
    conn.commit()
    conn.close()
    print(f"Set {done} logos in {d['name']}.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
