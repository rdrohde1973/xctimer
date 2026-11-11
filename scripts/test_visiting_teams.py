#!/usr/bin/env python3
"""Visiting teams (1.111.0): per-meet invite link, guest coaches, default-deny access.
    python scripts/test_visiting_teams.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import io, json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, guest                  # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}
MAIL = []
guest.send_email = lambda to, subject, html: MAIL.append((to, subject, html)) or True


def q(sql, *a):
    c = db.connect()
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


def client(uid=None):
    c = application.test_client()
    if uid:
        c.set_cookie(auth.SESSION_COOKIE, auth.create_session(uid))
    c.set_cookie("csrftoken", "x")
    return c


def last_link(to):
    html = next(h for t, s, h in reversed(MAIL) if t == to)
    return re.search(r'/guest/go/([\w-]+)', html).group(1)


# ---- fixtures: host district (Pryor) with HS + MS, a second district, a track and an XC meet
c = db.connect()
did = c.execute("INSERT INTO districts (name, slug, settings_json) VALUES ('Pryor','pryor',?)",
                (json.dumps({"grades": [6, 7, 8, 9, 10, 11, 12]}),)).lastrowid
other = c.execute("INSERT INTO districts (name, slug) VALUES ('Other','other')").lastrowid
hs = c.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Pryor High School')", (did,)).lastrowid
ms = c.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Pryor Middle School')", (did,)).lastrowid
c.execute("INSERT INTO athletes (school_id, name, grade, gender, does_track, does_xc, active) "
          "VALUES (?, 'Home Runner', 11, 'M', 1, 1, 1)", (hs,))
su = c.execute("INSERT INTO users (email, name, role) VALUES ('root@example.com','Root','super_admin')").lastrowid
hostcoach = c.execute("INSERT INTO users (district_id, email, name, role) VALUES (?, 'host@example.com','Host','coach')",
                      (did,)).lastrowid
c.execute("INSERT INTO user_schools (user_id, school_id) VALUES (?,?)", (hostcoach, hs))
elsewhere = c.execute("INSERT INTO users (district_id, email, name, role) VALUES (?, 'taken@example.com','T','coach')",
                      (other,)).lastrowid
trk = c.execute("INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token) "
                "VALUES (?, 'track', 'Mike Adair Invitational', '2099-03-27', ?, 'pubtrk')", (did, hs)).lastrowid
xc = c.execute("INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token) "
               "VALUES (?, 'xc', 'Short Track XC Invite', '2099-09-18', ?, 'pubxc')", (did, hs)).lastrowid
old = c.execute("INSERT INTO meets (district_id, sport, name, date, host_school_id, public_token, guest_token) "
                "VALUES (?, 'xc', 'Last Year', '2020-09-18', ?, 'pubold', 'oldtoken')", (did, hs)).lastrowid
for m_ in (trk, xc):
    c.execute("INSERT INTO meet_schools (meet_id, school_id) VALUES (?,?)", (m_, hs))
    c.execute("INSERT INTO races (meet_id, name, capture_mode) VALUES (?, 'Boys', 'tapselect')", (m_,))
ev100 = c.execute("SELECT id FROM events WHERE name='100m'").fetchone()[0]
me100 = c.execute("INSERT INTO meet_events (meet_id, event_id, gender, grade) VALUES (?,?, 'M', '')", (trk, ev100)).lastrowid
c.commit(); c.close()

# ---- 1. host (a coach of the host school, not an admin) creates the invite link
host = client(hostcoach)
page = host.get(f"/meets/{trk}").get_data(as_text=True)
assert "Visiting teams" in page and "Create invite link" in page
assert host.post(f"/meets/{trk}/guests/link", headers=H).status_code == 302
tok = q("SELECT guest_token FROM meets WHERE id=?", trk)[0][0]
assert tok and f"/join/{tok}" in host.get(f"/meets/{trk}").get_data(as_text=True)
assert host.get(f"/meets/{trk}/guests/qr.png").data[:4] == b"\x89PNG"
print("PASS 1: the host school's coach creates one invite link (and QR) for the meet")

# ---- 2. public join page + sign-up
anon = client()
r = anon.get(f"/join/{tok}")
assert r.status_code == 200 and b"Mike Adair Invitational" in r.data and b"Pryor High School" in r.data
assert anon.get("/join/nope").status_code == 404
assert b"closed" in anon.get("/join/oldtoken").data and anon.post("/join/oldtoken", data={"school": "X", "email": "a@b.co"}, headers=H).status_code == 404
r = anon.post(f"/join/{tok}", data={"school": "  Claremore  High School ", "name": "Coach Lee", "email": "Lee@Claremore.example"}, headers=H)
assert r.status_code == 200 and b"Check your email" in r.data, r.data[:300]
gs = q("SELECT * FROM schools WHERE guest=1")
assert len(gs) == 1 and gs[0]["name"] == "Claremore High School" and gs[0]["district_id"] == did
clar = gs[0]["id"]
assert q("SELECT 1 FROM meet_schools WHERE meet_id=? AND school_id=?", trk, clar)
assert MAIL[-1][0] == "lee@claremore.example" and "Mike Adair Invitational" in MAIL[-1][1]
assert not q("SELECT 1 FROM users WHERE email='lee@claremore.example'")
print("PASS 2: a visiting coach signs up from the link; a guest school is created and attached, no user account")

# ---- 3. an email that already has an XCTimer login elsewhere still works as a guest
r = anon.post(f"/join/{tok}", data={"school": "Oologah", "email": "taken@example.com"}, headers=H)
assert r.status_code == 200 and b"Check your email" in r.data
assert q("SELECT 1 FROM guest_coaches WHERE email='taken@example.com'")
print("PASS 3: a coach who already has a login in another district can still be a visiting coach")

# ---- 4. roster privacy: nobody can claim a registered team; home schools are refused
r = anon.post(f"/join/{tok}", data={"school": "claremore high school", "email": "stranger@example.com"}, headers=H)
assert r.status_code == 400 and b"already registered" in r.data
assert not q("SELECT 1 FROM guest_coaches WHERE email='stranger@example.com'")
r = anon.post(f"/join/{tok}", data={"school": "pryor middle school", "email": "x@example.com"}, headers=H)
assert r.status_code == 400 and b"host-district school" in r.data
assert anon.post(f"/join/{tok}", data={"school": "", "email": "nope"}, headers=H).status_code == 400
n = len(MAIL)
r = anon.post(f"/join/{tok}", data={"school": "CLAREMORE HIGH SCHOOL", "email": "lee@claremore.example"}, headers=H)
assert r.status_code == 200 and len(MAIL) == n + 1 and len(q("SELECT 1 FROM schools WHERE guest=1")) == 2
print("PASS 4: a stranger cannot claim a registered team; the real coach gets a fresh link; no duplicates")

# ---- 5. sign in by link
old_link = re.search(r'/guest/go/([\w-]+)', MAIL[0][2]).group(1)
assert anon.get(f"/guest/go/{old_link}").status_code == 404            # replaced by the fresh link
lee = client()
r = lee.get(f"/guest/go/{last_link('lee@claremore.example')}")
assert r.status_code == 302 and r.headers["Location"].endswith("/guest")
home = lee.get("/guest")
assert home.status_code == 200 and b"Claremore High School" in home.data and b"Mike Adair Invitational" in home.data
assert b"visiting coach" in home.data and b"/insights" not in home.data and b"/users" not in home.data
assert lee.get("/").headers["Location"].endswith("/guest")
print("PASS 5: the emailed link signs the coach in to a team page; old links stop working")

# ---- 6. roster + entries
assert lee.get(f"/schools/{clar}").status_code == 200
for nm, gr, gx in (("Vis Sprinter", 11, "M"), ("Vis Miler", 10, "F")):
    r = lee.post(f"/schools/{clar}/athletes", data={"name": nm, "grade": gr, "gender": gx, "does_track": "1", "does_xc": "1"}, headers=H)
    assert r.status_code == 302, r.status_code
aid = {r["name"]: r["id"] for r in q("SELECT id, name FROM athletes WHERE school_id=?", clar)}
assert len(aid) == 2
assert len(q("SELECT 1 FROM meet_bibs mb JOIN athletes a ON a.id=mb.athlete_id WHERE mb.meet_id=? AND a.school_id=?", trk, clar)) == 2
apage = lee.get(f"/meets/{trk}/assign?school={clar}")
assert apage.status_code == 200 and b"Vis Sprinter" in apage.data and b"Home Runner" not in apage.data
box = re.search(r'name="([^"]+)"[^>]*value="([^"]*)"[^>]*data-ath="%d"' % aid["Vis Sprinter"], apage.get_data(as_text=True)) \
    or re.search(r'data-ath="%d"[^>]*name="([^"]+)"[^>]*value="([^"]*)"' % aid["Vis Sprinter"], apage.get_data(as_text=True))
assert box, "entry checkbox not found"
r = lee.post(f"/meets/{trk}/assign?school={clar}", data={"school_id": str(clar), box.group(1): box.group(2)}, headers=H)
assert r.status_code in (200, 302), r.status_code
assert q("SELECT 1 FROM entries WHERE meet_event_id=? AND runner_id=?", me100, aid["Vis Sprinter"]), "entry not saved"
assert lee.get(f"/meets/{trk}").status_code == 200 and lee.get(f"/meets/{trk}/track-results").status_code == 200
assert lee.get(f"/meets/{trk}/school/{clar}/biblist.pdf").data[:4] == b"%PDF"
assert lee.get("/roster-template.xlsx").status_code == 200
r = lee.post(f"/schools/{clar}/import/commit", json={"athletes": [{"name": "Imported Kid", "grade": 9, "gender": "F"}]}, headers=H)
assert r.status_code == 200 and q("SELECT 1 FROM athletes WHERE school_id=? AND name='Imported Kid'", clar), r.data[:200]
print("PASS 6: the visiting coach adds athletes, they get meet bibs, and enters one in an event")

# ---- 7. default-deny: everything else is closed
deny = [("GET", f"/schools/{hs}"), ("GET", f"/meets/{xc}"), ("GET", f"/meets/{trk}/meet-day"),
        ("GET", f"/meets/{trk}/school/{hs}/biblist.pdf"), ("GET", "/insights"), ("GET", "/users"),
        ("GET", "/dashboard"), ("GET", f"/meets/{trk}/heatsheets.pdf"), ("GET", f"/meet-events/{me100}"),
        ("GET", f"/schools/{clar}/champ"), ("GET", f"/meets/{trk}/timer-qr.png")]
for meth, path in deny:
    r = lee.open(path, method=meth, headers=H)
    assert r.status_code in (403, 404), (meth, path, r.status_code)
posts = [(f"/meets", {"name": "My TT", "sport": "xc", "date": "2099-01-01", "time_trial": "1"}),
         (f"/meets/{trk}/schools", {"school_ids": [str(clar)]}), (f"/meets/{trk}/host", {"host_school_id": str(clar)}),
         (f"/meets/{trk}/guests/link", {}), (f"/meets/{trk}/guests/add", {"school": "Z", "email": "z@z.co"}),
         (f"/meets/{trk}/track-setup", {}), (f"/meets/{trk}/events", {"event_ids": str(ev100)}),
         (f"/meet-events/{me100}/marks", {}), (f"/meets/{trk}/pit/post", {}), (f"/schools/{hs}/athletes", {"name": "Hack"}),
         (f"/schools/{clar}/edit", {"name": "Renamed"}), ("/users", {"email": "a@b.co", "role": "coach"})]
for path, data in posts:
    r = lee.post(path, data=data, headers=H)
    assert r.status_code in (403, 404), (path, r.status_code)
assert lee.get("/phone").headers["Location"].endswith("/guest")
assert lee.get(f"/phone/meet/{trk}").headers["Location"].endswith("/guest")
assert not q("SELECT 1 FROM meets WHERE name='My TT'") and not q("SELECT 1 FROM athletes WHERE name='Hack'")
assert q("SELECT host_school_id FROM meets WHERE id=?", trk)[0][0] == hs
home_ath = q("SELECT id FROM athletes WHERE name='Home Runner'")[0][0]
assert lee.post(f"/athletes/{home_ath}/edit", json={"name": "Hacked"}, headers=H).status_code == 403
assert lee.get(f"/r/pubtrk").status_code == 200                              # public pages still open
print("PASS 7: timing, setup, other schools, other meets, insights and admin pages are all refused")

# ---- 8. host view, host-added team, second coach, resend, remove
page = host.get(f"/meets/{trk}").get_data(as_text=True)
assert "Claremore High School" in page and "3 athletes" in page and "lee@claremore.example" in page and "signed in" in page
hostsel = re.search(r'<select name="host_school_id".*?</select>', page, re.S).group(0)
assert "Pryor High School" in hostsel and "Claremore" not in hostsel, "a visiting team must not be offered as host"
r = host.post(f"/meets/{trk}/guests/add", data={"school": "Claremore High School", "email": "asst@claremore.example"}, headers=H)
assert r.status_code == 302 and "msg=" in r.headers["Location"] and MAIL[-1][0] == "asst@claremore.example"
r = host.post(f"/meets/{trk}/guests/add", data={"school": "Pryor Middle School", "email": "a@b.co"}, headers=H)
assert "err=" in r.headers["Location"]
gid = q("SELECT id FROM guest_coaches WHERE email='asst@claremore.example'")[0][0]
n = len(MAIL)
assert host.post(f"/meets/{trk}/guests/{gid}/resend", headers=H).status_code == 302 and len(MAIL) == n + 1
asst = client(); asst.get(f"/guest/go/{last_link('asst@claremore.example')}")
assert asst.get("/guest").status_code == 200
assert host.post(f"/meets/{trk}/guests/{gid}/remove", headers=H).status_code == 302
assert asst.get("/guest").status_code == 302 and not q("SELECT 1 FROM guest_coaches WHERE id=?", gid)
assert host.post(f"/meets/{xc}/guests/{q('SELECT id FROM guest_coaches')[0][0]}/resend", headers=H).status_code == 404
other_admin = c2 = db.connect(); oa = c2.execute("INSERT INTO users (district_id, email, name, role) VALUES (?, 'oa@example.com','OA','district_admin')", (other,)).lastrowid; c2.commit(); c2.close()
assert client(oa).post(f"/meets/{trk}/guests/link", headers=H).status_code == 403
print("PASS 8: host sees roster status, adds a second coach, resends and removes access; other districts cannot")

# ---- 9. reuse at the next meet, link rotation, cleanup
assert host.post(f"/meets/{xc}/guests/link", headers=H).status_code == 302
xtok = q("SELECT guest_token FROM meets WHERE id=?", xc)[0][0]
r = anon.post(f"/join/{xtok}", data={"school": "Claremore High School", "email": "lee@claremore.example"}, headers=H)
assert r.status_code == 200 and len(q("SELECT 1 FROM schools WHERE guest=1")) == 2
assert len(q("SELECT 1 FROM meet_bibs mb JOIN athletes a ON a.id=mb.athlete_id WHERE mb.meet_id=? AND a.school_id=?", xc, clar)) >= 2
lee2 = client(); lee2.get(f"/guest/go/{last_link('lee@claremore.example')}")
assert b"Short Track XC Invite" in lee2.get("/guest").data and lee2.get(f"/meets/{xc}").status_code == 200
host.post(f"/meets/{trk}/guests/link", data={"rotate": "1"}, headers=H)
assert anon.get(f"/join/{tok}").status_code == 404 and lee2.get("/guest").status_code == 200
root = client(su)
with root.session_transaction() as s:
    s["active_district_id"] = did
assert "visiting" in root.get("/schools").get_data(as_text=True)
r = root.post("/users", data={"email": "taken@example.com", "role": "coach", "district_id": str(did), "school_id": str(hs)}, headers=H)
assert r.status_code == 302 and "err=" in r.headers["Location"] and "Visiting" in r.headers["Location"]
assert "2 schools" in root.get("/districts").get_data(as_text=True)
assert root.post(f"/schools/{clar}/delete", headers=H).status_code == 302
assert not q("SELECT 1 FROM guest_coaches WHERE school_id=?", clar) and lee2.get("/guest").status_code == 302
print("PASS 9: a returning team keeps its roster; rotating the link keeps existing coaches; deletes clean up")
print("ALL PASS")
