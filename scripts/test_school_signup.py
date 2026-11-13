#!/usr/bin/env python3
"""Self-serve school sign-up at /start, and AI Insights as a subscription feature (1.113.0).
    python scripts/test_school_signup.py
Uses a temp DB (XCTIMER_DB); emails and the AI call are captured, never sent."""
import json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, billing, signup, ai   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}

MAIL = []
signup.send_email = lambda to, subject, html: MAIL.append((to, subject, html))
ASKED = []
ai.claude_chat = lambda *a, **k: ASKED.append(a) or "The answer."


def anon(ip="10.0.0.1"):
    w = application.test_client()
    w.set_cookie("csrftoken", "x")
    w.environ_base["REMOTE_ADDR"] = ip
    return w


def q(sql, *a):
    conn = db.connect()
    rows = conn.execute(sql, a).fetchall()
    conn.close()
    return rows


FORM = dict(school="Maple Grove Middle School", district="Maple Grove School District", level="ms",
            state="Utah", who="Pat Coach", email="Pat@MapleGrove.example")

# 1. the page is public and linked from the marketing and pricing pages
w = anon()
page = w.get("/start")
assert page.status_code == 200 and b"Set up your school on XCTimer" in page.data and b"$100" in page.data
assert 'href="/start"' in w.get("/welcome").get_data(as_text=True)
pricing = w.get("/pricing").get_data(as_text=True)
assert 'href="/start">Set up your school' in pricing and "AI Insights" in pricing and "Priority support" in pricing
print("PASS 1: /start is public and linked from the marketing and pricing pages")

# 2. a sign-up creates a pay-per-meet district, the school, and an admin login for the coach
r = w.post("/start", data=FORM, headers=H)
assert r.status_code == 200 and b"Check your email" in r.data and b"pat@maplegrove.example" in r.data
d = q("SELECT * FROM districts")[0]
s = json.loads(d["settings_json"])
assert d["name"] == "Maple Grove School District" and s["plan"] == "per_meet" and "grades" not in s
assert s["self_serve"]["by"] == "pat@maplegrove.example" and s["self_serve"]["state"] == "Utah"
assert s["email_domains"] == ["maplegrove.example"]          # the next coach at this domain joins this district
sch = q("SELECT * FROM schools")[0]
u = q("SELECT * FROM users")[0]
assert sch["district_id"] == d["id"] and sch["name"] == "Maple Grove Middle School"
assert u["role"] == "coach" and u["district_id"] == d["id"] and not u["password_hash"] and not u["is_demo"]
assert not q("SELECT 1 FROM users WHERE role='district_admin'")           # admins come with the subscription
assert q("SELECT school_id FROM user_schools WHERE user_id=?", u["id"])[0][0] == sch["id"]
(to1, subj1, html1), (to2, subj2, html2) = MAIL
assert to1 == "pat@maplegrove.example" and "Maple Grove Middle School" in subj1 and u["setup_token"] in html1
assert to2 == "rob@xctimer.com" and "New school sign-up" in subj2 and "Pat Coach" in html2 and "Utah" in html2
print("PASS 2: sign-up creates the district (Pay per meet), school and a coach login, and emails both sides")

# 3. the emailed link sets a password and lands on a dashboard that says what to do next
c = anon()
assert c.get(f"/setup?token={u['setup_token']}").status_code == 200
r = c.post("/setup", data={"token": u["setup_token"], "password": "correct horse", "confirm": "correct horse"}, headers=H)
assert r.status_code == 302 and r.headers["Location"].endswith("/schools")
r = c.get("/schools")
assert r.status_code == 302 and r.headers["Location"].endswith(f"/schools/{sch['id']}")   # straight to the roster
home = c.get(f"/schools/{sch['id']}").get_data(as_text=True)
assert "Getting started" in home and "Add your roster</b> on this page" in home and "Go live for $100" in home
assert c.get("/users").status_code == 403 and 'href="/users"' not in home               # a coach, not an admin
assert c.post("/schools", data={"name": "Another School"}, headers=H).status_code == 403
assert "Create a meet" in c.get("/meets").get_data(as_text=True)
r = c.post("/meets", data=dict(name="Maple Invite", sport="xc", date="2027-09-01", school_ids=[sch["id"]]), headers=H)
mid = int(r.headers["Location"].rsplit("/", 1)[1])
setup = c.get(f"/meets/{mid}").get_data(as_text=True)
assert "Go live: $100 for this meet" in setup
rid = q("SELECT id FROM races WHERE meet_id=?", mid)[0][0]
assert c.post(f"/races/{rid}/start", json={}, headers=H).status_code == 403          # locked until paid
c.post(f"/schools/{sch['id']}/athletes", data={"name": "Ada Runner", "grade": "8", "gender": "F"}, headers=H)
assert q("SELECT COUNT(*) FROM athletes")[0][0] == 1
assert "Getting started" not in c.get(f"/schools/{sch['id']}").get_data(as_text=True)   # roster + meet: card retires
assert f"/meets/{mid}/guest-invite" in setup or "Visiting teams" in setup            # the coach can invite visitors
assert anon().get("/start").status_code == 200 and c.get("/start").status_code == 302  # signed in: go home
print("PASS 3: the setup link signs them in; they can build a roster and a meet, which stays locked until paid")

# 4. pay per meet keeps the how-to help; questions about their own data belong to the subscription
ins = c.get("/insights").get_data(as_text=True)
assert 'id="q"' in ins and "Ask about your own data with the district subscription" in ins
assert "How do I import my roster?" in ins and "Who is my fastest 200m runner?" not in ins
r = c.post("/api/insights/ask", json={"question": "Who is fastest?"}, headers=H)
assert r.status_code == 200 and r.get_json()["help_only"] and len(ASKED) == 1
system, user = ASKED[0][0], ASKED[0][1]
assert "NO access" in system and "district subscription" in system and "HOW XCTIMER WORKS" in system
assert "DATA DIGEST" not in user and "Ada Runner" not in user and "Ada Runner" not in system   # no roster leaves
conn = db.connect()
billing.set_district_plan(conn, d["id"], "subscription"); conn.commit(); conn.close()
ins = c.get("/insights").get_data(as_text=True)
assert 'id="q"' in ins and "Who is my fastest 200m runner?" in ins and "district subscription" not in ins
r = c.post("/api/insights/ask", json={"question": "Who is fastest?"}, headers=H)
assert r.status_code == 200 and "help_only" not in r.get_json() and len(ASKED) == 2
assert "DATA DIGEST" in ASKED[1][1] and "Ada Runner" in ASKED[1][1]                  # subscribers get their data
conn = db.connect()
billing.set_district_plan(conn, d["id"], "per_meet"); conn.commit(); conn.close()
conn = db.connect()
sup = conn.execute("INSERT INTO users (email, name, role) VALUES ('root@x.example','Root','super_admin')").lastrowid
conn.commit(); conn.close()
root = application.test_client(); root.set_cookie(auth.SESSION_COOKIE, auth.create_session(sup)); root.set_cookie("csrftoken", "x")
assert "Who is my fastest 200m runner?" in root.get("/insights").get_data(as_text=True)   # Super Admin never limited
dpage = root.get("/districts").get_data(as_text=True)
assert "Self-serve</span>" in dpage and "pat@maplegrove.example" in dpage and "Pay per meet</span>" in dpage
print("PASS 4: pay-per-meet districts get how-to help only (no data sent); subscriptions get data answers")

# 5. an address that already has a login gets the same page and an honest email; nothing is created
MAIL.clear()
r = anon("10.0.0.2").post("/start", data=dict(FORM, school="Sneaky Second School"), headers=H)
assert r.status_code == 200 and b"Check your email" in r.data
assert len(q("SELECT 1 FROM districts")) == 1 and len(MAIL) == 1 and "already has an account" in MAIL[0][2]
conn = db.connect()
conn.execute("INSERT INTO users (district_id, email, name, role, setup_token) VALUES (?,?,?,?,?)",
             (d["id"], "invited@maplegrove.example", "Invited", "coach", "oldtoken"))
conn.commit(); conn.close()
MAIL.clear()
r = anon("10.0.0.2").post("/start", data=dict(FORM, email="invited@maplegrove.example"), headers=H)
assert b"Is this your school?" in r.data and not MAIL        # same question as for a brand-new address
anon("10.0.0.2").post("/start", data=dict(FORM, email="invited@maplegrove.example", match=str(sch["id"])), headers=H)
tok = q("SELECT setup_token FROM users WHERE email='invited@maplegrove.example'")[0][0]
assert len(MAIL) == 1 and tok != "oldtoken" and f"/setup?token={tok}" in MAIL[0][2]
print("PASS 5: signing up with an existing address creates nothing and never reveals the account on the page")

# 6. a matching district name makes a SEPARATE district and flags it to the operator
MAIL.clear()
r = anon("10.0.0.3").post("/start", data=dict(FORM, school="Maple Grove High School", level="hs",
                                             email="lee@elsewhere.example", who="Lee Coach"), headers=H)
assert b"Check your email" in r.data                          # a different email domain: no question asked
ds = q("SELECT * FROM districts ORDER BY id")
assert len(ds) == 2 and ds[1]["slug"] != ds[0]["slug"] and json.loads(ds[1]["settings_json"])["grades"] == [9, 10, 11, 12]
assert q("SELECT district_id FROM users WHERE email='lee@elsewhere.example'")[0][0] == ds[1]["id"]
assert "already exists" in MAIL[1][2]
lee = application.test_client()
lee.set_cookie(auth.SESSION_COOKIE, auth.create_session(q("SELECT id FROM users WHERE email='lee@elsewhere.example'")[0][0]))
assert lee.get(f"/schools/{sch['id']}").status_code in (403, 404)                    # cannot see the other school
assert lee.get(f"/meets/{mid}").status_code == 403
# no district given: the school name is used
anon("10.0.0.4").post("/start", data=dict(FORM, school="Lone Pine Academy", district="", level="both",
                                         email="sam@lonepine.example"), headers=H)
lp = q("SELECT * FROM districts WHERE name='Lone Pine Academy'")[0]
assert json.loads(lp["settings_json"])["grades"] == [6, 7, 8, 9, 10, 11, 12]
print("PASS 6: a same-named district is kept separate (no roster leak) and flagged in the operator email")

# 7. junk is refused: bad input, the bot trap, and too many from one network
n = len(q("SELECT 1 FROM districts"))
assert anon("10.0.0.5").post("/start", data=dict(FORM, email="not-an-email"), headers=H).status_code == 400
assert anon("10.0.0.5").post("/start", data=dict(FORM, school="", email="a@b.example"), headers=H).status_code == 400
r = anon("10.0.0.5").post("/start", data=dict(FORM, email="bot@spam.example", website="http://spam"), headers=H)
assert r.status_code == 200 and not q("SELECT 1 FROM users WHERE email='bot@spam.example'")
codes = [anon("10.0.0.9").post("/start", data=dict(FORM, school=f"Flood {i}", email=f"f{i}@flood{i}.example"),
                               headers=H).status_code for i in range(7)]
assert codes == [200] * 5 + [429] * 2, codes
assert len(q("SELECT 1 FROM districts")) == n + 5
assert application.test_client().post("/start", data=FORM).status_code == 403        # no CSRF token
print("PASS 7: bad input, the bot trap, floods and missing security tokens are all refused")

# 8. both assistants know the phone scanner and push the finish-order bib board
from xctimerpkg import insights, road                                              # noqa: E402
for prompt in (insights._SYS, insights._SYS_HELP, road._HOST_HELP_SYS):
    prompt = " ".join(prompt.split())                    # the guides are hard-wrapped
    assert "BIB BOARD" in prompt and "poster board" in prompt and "STRONGLY recommend" in prompt
    assert "📷" in prompt and "in the order they finished" in prompt
    assert "only once per race" in prompt and "no duplicate scans" in prompt
assert "How do I use the phone scanner?" in c.get("/insights").get_data(as_text=True)      # pay per meet
assert "How do I use the phone scanner?" in root.get("/insights").get_data(as_text=True)   # full Insights
print("PASS 8: the assistants explain the phone scanner and strongly recommend the bib board")

# 9. "Ask the Ref" also shows for a race director who creates events from the Events page
conn = db.connect()
org = conn.execute("INSERT INTO organizers (name, slug) VALUES ('Town Rec','town-rec')").lastrowid
rd = conn.execute("INSERT INTO users (organizer_id, email, name, role) VALUES (?,?,?,?)",
                  (org, "director@townrec.example", "Dee Rector", "race_director")).lastrowid
conn.commit(); conn.close()
dw = application.test_client(); dw.set_cookie(auth.SESSION_COOKIE, auth.create_session(rd)); dw.set_cookie("csrftoken", "x")
r = dw.post("/events", data={"name": "Town 5K", "date": "2027-05-01"}, headers=H)
ev = int(re.search(r"/meets/(\d+)", r.headers["Location"]).group(1))
for path in ("/events", f"/meets/{ev}", f"/meets/{ev}/participants"):
    assert "Ask the Ref" in dw.get(path).get_data(as_text=True), path
ASKED.clear()
r = dw.post("/host/chat", json={"message": "How do I use the phone scanner?"}, headers=H)
assert r.status_code == 200 and r.get_json()["reply"] == "The answer." and len(ASKED) == 1
guide = " ".join(ASKED[0][0].split())
assert "BIB BOARD" in guide and "xctimer.com/login" in guide and "Events page" in guide
assert "$100" not in guide and "xctimer.com/host" not in guide and "auto-deletes" not in guide
own = " ".join(road._HOST_HELP_SYS.split())                                           # self-serve guide unchanged
assert "$100 per event" in own and "xctimer.com/host" in own and "auto-deletes 30 days" in own
assert "Ask the Ref" not in c.get("/meets").get_data(as_text=True)                     # a school coach: no Ref
assert c.post("/host/chat", json={"message": "hi"}, headers=H).status_code == 403
print("PASS 9: race directors get the Ref on their event pages, with a guide that fits their account")

# 10. a coach whose email domain is exactly an existing district's joins that district
def users_of(email):
    return q("SELECT u.*, (SELECT group_concat(school_id) FROM user_schools WHERE user_id=u.id) AS sids "
             "FROM users u WHERE email=?", email)

n_d = len(q("SELECT 1 FROM districts"))
n_s = len(q("SELECT 1 FROM schools"))
# a NEW school at the district's domain is added to that district: no new district, no question
MAIL.clear()
r = anon("10.0.1.1").post("/start", data=dict(FORM, school="Oak Hollow Middle School", district="whatever they type",
                                             email="Kim@MapleGrove.example", who="Kim Coach"), headers=H)
assert r.status_code == 200 and b"Check your email" in r.data
assert len(q("SELECT 1 FROM districts")) == n_d and len(q("SELECT 1 FROM schools")) == n_s + 1
oak = q("SELECT * FROM schools WHERE name='Oak Hollow Middle School'")[0]
kim = users_of("kim@maplegrove.example")[0]
assert oak["district_id"] == d["id"] and kim["district_id"] == d["id"] and kim["role"] == "coach"
assert kim["sids"] == str(oak["id"]) and not kim["password_hash"]
(to1, subj1, html1), (to2, subj2, html2) = MAIL
assert to1 == "kim@maplegrove.example" and "has been added to <b>Maple Grove School District</b>" in html1
assert kim["setup_token"] in html1 and "$100 when a meet goes live" in html1
assert to2 == "rob@xctimer.com" and subj2 == "School joined Maple Grove School District: Oak Hollow Middle School"
assert "email domain maplegrove.example" in html2 and "not a duplicate" in html2 and "bill the school" not in html2

# a school that LOOKS like one already there: they are asked first, and nothing is created yet
MAIL.clear()
before = (len(q("SELECT 1 FROM users")), len(q("SELECT 1 FROM schools")))
r = anon("10.0.1.2").post("/start", data=dict(FORM, school="maple grove jr. high", email="jo@maplegrove.example", who="Jo Coach"), headers=H)
page = r.get_data(as_text=True)
assert r.status_code == 200 and "Is this your school?" in page and "Maple Grove School District" in page
assert f'name="match" value="{sch["id"]}"' in page and "Yes, I coach at Maple Grove Middle School" in page
assert 'name="match" value="new"' in page and "No, add maple grove jr. high as a new school" in page
assert "Oak Hollow" not in page                               # only schools that look like theirs are shown
assert 'name="email" value="jo@maplegrove.example"' in page and 'name="who" value="Jo Coach"' in page
assert not MAIL and before == (len(q("SELECT 1 FROM users")), len(q("SELECT 1 FROM schools")))

# "Yes": added as a coach of the EXISTING school; no new school, no new district
r = anon("10.0.1.2").post("/start", data=dict(FORM, school="maple grove jr. high", email="jo@maplegrove.example",
                                             who="Jo Coach", match=str(sch["id"])), headers=H)
assert b"Check your email" in r.data
jo = users_of("jo@maplegrove.example")[0]
assert jo["role"] == "coach" and jo["district_id"] == d["id"] and jo["sids"] == str(sch["id"])
assert len(q("SELECT 1 FROM schools")) == before[1] and len(q("SELECT 1 FROM districts")) == n_d
assert "added as a coach for <b>Maple Grove Middle School</b>" in MAIL[0][2] and jo["setup_token"] in MAIL[0][2]
assert MAIL[1][1] == "Coach joined Maple Grove Middle School: Jo Coach" and "maple grove jr. high" in MAIL[1][2]
jw = anon()
jw.post("/setup", data={"token": jo["setup_token"], "password": "correct horse", "confirm": "correct horse"}, headers=H)
roster = jw.get(f"/schools/{sch['id']}")
assert roster.status_code == 200 and "Ada Runner" in roster.get_data(as_text=True)          # the existing roster
assert jw.get(f"/schools/{oak['id']}").status_code in (403, 404)                          # not the other school

# "No, add it as a new school": a second school with a similar name in the same district
MAIL.clear()
r = anon("10.0.1.3").post("/start", data=dict(FORM, school="Maple Grove High School", email="hs@maplegrove.example",
                                             who="Hy Coach", match="new"), headers=H)
assert b"Check your email" in r.data
hs = q("SELECT * FROM schools WHERE name='Maple Grove High School' AND district_id=?", d["id"])
assert len(hs) == 1 and users_of("hs@maplegrove.example")[0]["sids"] == str(hs[0]["id"])
assert len(q("SELECT 1 FROM districts")) == n_d

# a made-up or foreign school id is not a way in: they are asked again and nothing is created
lone = q("SELECT id FROM schools WHERE name='Lone Pine Academy'")[0][0]
for bad in (str(lone), "999999", "0", "x"):
    r = anon("10.0.1.4").post("/start", data=dict(FORM, email="eve@maplegrove.example", match=bad), headers=H)
    assert b"Is this your school?" in r.data, bad
assert not users_of("eve@maplegrove.example")

# public mail providers never match and are never recorded; a near-miss domain does not match
anon("10.0.1.5").post("/start", data=dict(FORM, school="Gmail Middle School", district="", email="a.coach@gmail.com"), headers=H)
anon("10.0.1.5").post("/start", data=dict(FORM, school="Other Gmail School", district="", email="b.coach@gmail.com"), headers=H)
g1, g2 = users_of("a.coach@gmail.com")[0], users_of("b.coach@gmail.com")[0]
assert g1["district_id"] != g2["district_id"]
assert "email_domains" not in json.loads(q("SELECT settings_json FROM districts WHERE id=?", g1["district_id"])[0][0])
for near in ("x@mail.maplegrove.example", "x@maplegrove.example.org", "x@notmaplegrove.example"):
    r = anon("10.0.1.6").post("/start", data=dict(FORM, email=near), headers=H)
    assert b"Check your email" in r.data, near
    assert users_of(near)[0]["district_id"] != d["id"], near
assert signup.parse_domains("@Alpine-District.org, gmail.com; bad_domain, k12.ut.us x") == ["alpine-district.org", "k12.ut.us"]

# Super Admin sets a district's domain on the Districts page; a subscription district says so to the operator
conn = db.connect()
big = conn.execute("INSERT INTO districts (name, slug, settings_json) VALUES ('Big Valley Schools','big-valley',?)",
                   (json.dumps({"plan": "subscription"}),)).lastrowid
bvs = conn.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Timberline')", (big,)).lastrowid
conn.commit(); conn.close()
assert c.post(f"/districts/{big}/email-domains", data={"domains": "bigvalley.example"}, headers=H).status_code == 403
assert root.post(f"/districts/{big}/email-domains", data={"domains": " @BigValley.example, gmail.com "}, headers=H).status_code == 302
assert signup.email_domains(q("SELECT settings_json FROM districts WHERE id=?", big)[0][0]) == ["bigvalley.example"]
assert 'value="bigvalley.example"' in root.get("/districts").get_data(as_text=True)
r = anon("10.0.1.7").post("/start", data=dict(FORM, school="Timberline Middle School", email="t@bigvalley.example", who="Tim"), headers=H)
assert b"Yes, I coach at Timberline" in r.data
MAIL.clear()
anon("10.0.1.7").post("/start", data=dict(FORM, school="Cedar Fort Middle", email="cf@bigvalley.example", who="Cee"), headers=H)
assert users_of("cf@bigvalley.example")[0]["district_id"] == big
assert "$100" not in MAIL[0][2] and "bill the school" in MAIL[1][2] and "Paid subscription" in MAIL[1][2]
# the same domain on two districts matches neither (a fresh district is made) and the page warns
root.post(f"/districts/{lp['id']}/email-domains", data={"domains": "bigvalley.example"}, headers=H)
assert "matches neither" in root.get("/districts").get_data(as_text=True)
anon("10.0.1.8").post("/start", data=dict(FORM, school="Timberline", email="amb@bigvalley.example"), headers=H)
amb = users_of("amb@bigvalley.example")[0]
assert amb["district_id"] not in (big, lp["id"])
root.post(f"/districts/{lp['id']}/email-domains", data={"domains": ""}, headers=H)             # cleared
assert "email_domains" not in json.loads(q("SELECT settings_json FROM districts WHERE id=?", lp["id"])[0][0])
print("PASS 10: an exact email-domain match joins the existing district; a look-alike school is confirmed first")
print("ALL PASS")
