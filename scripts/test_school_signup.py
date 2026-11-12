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
sch = q("SELECT * FROM schools")[0]
u = q("SELECT * FROM users")[0]
assert sch["district_id"] == d["id"] and sch["name"] == "Maple Grove Middle School"
assert u["role"] == "district_admin" and u["district_id"] == d["id"] and not u["password_hash"] and not u["is_demo"]
assert q("SELECT school_id FROM user_schools WHERE user_id=?", u["id"])[0][0] == sch["id"]
(to1, subj1, html1), (to2, subj2, html2) = MAIL
assert to1 == "pat@maplegrove.example" and "Maple Grove Middle School" in subj1 and u["setup_token"] in html1
assert to2 == "rob@xctimer.com" and "New school sign-up" in subj2 and "Pat Coach" in html2 and "Utah" in html2
print("PASS 2: sign-up creates the district (Pay per meet), school and admin login, and emails both sides")

# 3. the emailed link sets a password and lands on a dashboard that says what to do next
c = anon()
assert c.get(f"/setup?token={u['setup_token']}").status_code == 200
r = c.post("/setup", data={"token": u["setup_token"], "password": "correct horse", "confirm": "correct horse"}, headers=H)
assert r.status_code == 302 and r.headers["Location"].endswith("/dashboard")
dash = c.get("/dashboard").get_data(as_text=True)
assert "Getting started" in dash and f'/schools/{sch["id"]}' in dash and "Go live for $100" in dash
assert c.get(f"/schools/{sch['id']}").status_code == 200
r = c.post("/meets", data=dict(name="Maple Invite", sport="xc", date="2027-09-01", host_school_id=sch["id"],
                               school_ids=[sch["id"]]), headers=H)
mid = int(r.headers["Location"].rsplit("/", 1)[1])
setup = c.get(f"/meets/{mid}").get_data(as_text=True)
assert "Go live: $100 for this meet" in setup
rid = q("SELECT id FROM races WHERE meet_id=?", mid)[0][0]
assert c.post(f"/races/{rid}/start", json={}, headers=H).status_code == 403          # locked until paid
c.post(f"/schools/{sch['id']}/athletes", data={"name": "Ada Runner", "grade": "8", "gender": "F"}, headers=H)
assert q("SELECT COUNT(*) FROM athletes")[0][0] == 1
assert "Getting started" not in c.get("/dashboard").get_data(as_text=True)           # roster + meet: card retires
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
anon("10.0.0.2").post("/start", data=dict(FORM, email="invited@maplegrove.example"), headers=H)
tok = q("SELECT setup_token FROM users WHERE email='invited@maplegrove.example'")[0][0]
assert len(MAIL) == 1 and tok != "oldtoken" and f"/setup?token={tok}" in MAIL[0][2]
print("PASS 5: signing up with an existing address creates nothing and never reveals the account on the page")

# 6. a matching district name makes a SEPARATE district and flags it to the operator
MAIL.clear()
r = anon("10.0.0.3").post("/start", data=dict(FORM, school="Maple Grove High School", level="hs",
                                             email="lee@maplegrove.example", who="Lee Coach"), headers=H)
ds = q("SELECT * FROM districts ORDER BY id")
assert len(ds) == 2 and ds[1]["slug"] != ds[0]["slug"] and json.loads(ds[1]["settings_json"])["grades"] == [9, 10, 11, 12]
assert q("SELECT district_id FROM users WHERE email='lee@maplegrove.example'")[0][0] == ds[1]["id"]
assert "already exists" in MAIL[1][2]
lee = application.test_client()
lee.set_cookie(auth.SESSION_COOKIE, auth.create_session(q("SELECT id FROM users WHERE email='lee@maplegrove.example'")[0][0]))
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
codes = [anon("10.0.0.9").post("/start", data=dict(FORM, school=f"Flood {i}", email=f"f{i}@flood.example"),
                               headers=H).status_code for i in range(7)]
assert codes == [200] * 5 + [429] * 2, codes
assert len(q("SELECT 1 FROM districts")) == n + 5
assert application.test_client().post("/start", data=FORM).status_code == 403        # no CSRF token
print("PASS 7: bad input, the bot trap, floods and missing security tokens are all refused")
print("ALL PASS")
