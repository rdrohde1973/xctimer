#!/usr/bin/env python3
"""Demo (read-only) accounts (1.111.1). Run with a Python that has Flask installed:
    python scripts/test_demo_account.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, demo                   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}

c = db.connect()
ids = {}
for slug in ("demo", "real"):
    did = c.execute("INSERT INTO districts (name, slug) VALUES (?,?)", (slug.title(), slug)).lastrowid
    sid = c.execute("INSERT INTO schools (district_id, name) VALUES (?,?)", (did, f"{slug} school")).lastrowid
    c.execute("INSERT INTO athletes (school_id, name, grade, gender, does_xc, does_track, active) "
              "VALUES (?,?,8,'F',1,1,1)", (sid, "Zelda Quartermaine"))
    uid = c.execute("INSERT INTO users (district_id, email, name, role, is_demo) VALUES (?,?,?,?,1)",
                    (did, f"viewer@{slug}.example", "Viewer", "district_admin")).lastrowid
    c.execute("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)",
              (did, f"private.person@{slug}.example", "Coach", "coach"))
    ids[slug] = (did, sid, uid)
c.commit(); c.close()


def client(slug):
    w = application.test_client()
    w.set_cookie(auth.SESSION_COOKIE, auth.create_session(ids[slug][2]))
    w.set_cookie("csrftoken", "x")
    return w


for slug in ("demo", "real"):
    w, sid = client(slug), ids[slug][1]
    # 1. still read-only everywhere
    assert w.post(f"/schools/{sid}/athletes", data={"name": "X", "grade": "8", "gender": "F"}, headers=H).status_code == 403
    assert w.post("/meets", data={"name": "x", "sport": "track", "date": "2026-01-01"}, headers=H).status_code == 403
    # 2. no Users page, no Users link, no account emails
    r = w.get("/users")
    assert r.status_code == 403 and b"private.person" not in r.data, r.status_code
    home = w.get("/schools").get_data(as_text=True)
    assert 'href="/users"' not in home and 'href="/schools"' in home
    # 3. names: stored (fictional) in the Demo District, generated everywhere else
    roster = w.get(f"/schools/{sid}").get_data(as_text=True)
    assert ("Zelda Quartermaine" in roster) == (slug == "demo"), slug
    assert (demo.anon_name("Zelda Quartermaine") in roster) == (slug == "real"), slug
print("PASS 1: demo admins stay read-only and cannot open the Users page in any district")
print("PASS 2: Demo District shows its stored fictional names; a real district is still anonymized")

# a real (non-demo) district admin is untouched
c = db.connect()
uid = c.execute("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)",
                (ids["real"][0], "admin@real.example", "Admin", "district_admin")).lastrowid
c.commit(); c.close()
w = application.test_client(); w.set_cookie(auth.SESSION_COOKIE, auth.create_session(uid))
r = w.get("/users")
assert r.status_code == 200 and b"private.person@real.example" in r.data
assert 'href="/users"' in w.get("/schools").get_data(as_text=True)
assert "Zelda Quartermaine" in w.get(f"/schools/{ids['real'][1]}").get_data(as_text=True)
assert demo.mode_for(None) is None
print("PASS 3: ordinary district admins still see Users and real names")

# --- one phone app (1.111.2): no sign-in app card on Meets; the per-meet link is the way in
html = w.get("/meets").get_data(as_text=True)
assert "The app on your phone" not in html and "/phone/qr.png" not in html
assert w.get("/phone/qr.png").status_code == 404
c = db.connect()
mid = c.execute("INSERT INTO meets (district_id, sport, name, date, public_token) VALUES (?,?,?,?,?)",
                (ids["real"][0], "xc", "Dual", "2026-09-01", "pubtok")).lastrowid
c.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?,?,?)", (mid, "Boys", "tapselect"))
c.commit(); c.close()
day = w.get(f"/meets/{mid}/xc-day").get_data(as_text=True)
assert "Phone Timer App" in day and "/t/" in day
c = db.connect(); tok = c.execute("SELECT timer_token FROM meets WHERE id=?", (mid,)).fetchone()[0]; c.close()
helper = application.test_client()
r = helper.get(f"/t/{tok}")
assert r.status_code == 302 and r.headers["Location"].endswith("/phone")
page = helper.get("/phone").get_data(as_text=True)
assert "Dual" in page and "Boys" in page                      # no login, scoped to this meet
assert w.get("/phone").status_code == 200                      # a signed-in coach/admin can still open it
print("PASS 4: one phone app -- no sign-in card on Meets, the per-meet link still opens the timer")

# --- the meet-day QR also sits at the top of the Setup page, for people who may time the meet
setup = w.get(f"/meets/{mid}").get_data(as_text=True)
assert f"/meets/{mid}/timer-qr.png" in setup and f"/t/{tok}" in setup
assert setup.index("<h1>Dual</h1>") < setup.index("timer-qr.png") < setup.index("Rename meet")   # by the name, above the tabs
assert w.get(f"/meets/{mid}/timer-qr.png").status_code == 200
print("PASS 5: the Phone Timer App QR is at the top of the Setup page")
