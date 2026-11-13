#!/usr/bin/env python3
"""The seven errors found in the browser QA pass of 2026-11-13, each pinned (1.120.0).
    python scripts/test_qa_fixes.py
Temp DB (XCTIMER_DB), fake Square, stubbed AI; never touches real data or the network."""
import io, json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

import xctimerpkg                                                      # noqa: E402
sys.modules["xctimer"] = xctimerpkg
from xctimerpkg import app as appmod, db, auth, ai, billing, road, square   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}

LINKS, ORDERS, OK_ORDERS = [], {}, set()
square.is_configured = lambda: True
def _link(name, amount_cents, redirect_url, note):
    LINKS.append(dict(name=name, amount=amount_cents, note=note))
    return "https://square.link/u/fake"
square.create_payment_link = _link
square.completed_order = lambda oid: ORDERS.get(oid)
square.order_ok = lambda oid, expect_note_substr=None: oid in OK_ORDERS


def q(sql, *a):
    conn = db.connect()
    rows = conn.execute(sql, a).fetchall()
    conn.close()
    return rows


def ex(sql, *a):
    conn = db.connect()
    rid = conn.execute(sql, a).lastrowid
    conn.commit()
    conn.close()
    return rid


def client(uid=None, kind=None, meet=None):
    w = application.test_client()
    w.set_cookie("csrftoken", "x")
    if uid and kind:                      # a self-serve host's event-owner session
        tok = f"tok-{uid}-{meet}"
        ex("INSERT OR REPLACE INTO sessions (token, user_id, kind, meet_id, created_at, expires) VALUES (?,?,?,?,?,?)",
           tok, uid, kind, meet, auth._iso(auth._now()), auth._iso(auth._now() + auth.timedelta(days=1)))
        w.set_cookie(auth.SESSION_COOKIE, tok)
    elif uid:
        w.set_cookie(auth.SESSION_COOKIE, auth.create_session(uid))
    return w


# ---- fixtures: a pay-per-meet school, a coach, an XC meet that is live, a track meet -----
DID = ex("INSERT INTO districts (name, slug, settings_json) VALUES ('Payper','payper',?)", json.dumps({"plan": "per_meet"}))
SID = ex("INSERT INTO schools (district_id, name) VALUES (?, 'Payper North')", DID)
ATH = [ex("INSERT INTO athletes (school_id, name, grade, gender, does_xc, does_track, active) VALUES (?,?,8,'M',1,1,1)",
          SID, f"Runner {i}") for i in range(1, 4)]
COACH = ex("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)", DID, "coach@payper.example", "Coach", "coach")
ex("INSERT INTO user_schools (user_id, school_id) VALUES (?,?)", COACH, SID)
for code, pct, first in (("HALF", 50, 1), ("FREE", 100, 0)):
    ex("INSERT INTO promo_codes (code, active, percent_off, first_event_only, used_count) VALUES (?,1,?,?,0)", code, pct, first)
c = client(COACH)
used = lambda code: q("SELECT used_count FROM promo_codes WHERE code=?", code)[0][0]      # noqa: E731
r = c.post("/meets", data=dict(name="Live Meet", sport="xc", date="2027-09-01", school_ids=[SID]), headers=H)
MID = int(r.headers["Location"].rsplit("/", 1)[1])
assert c.post(f"/meets/{MID}/meet-fee/redeem", json={"code": "FREE"}, headers=H).get_json()["paid"]
RID = q("SELECT id FROM races WHERE meet_id=? ORDER BY id", MID)[0][0]
BIB = {r["athlete_id"]: r["bib"] for r in q("SELECT athlete_id, bib FROM meet_bibs WHERE meet_id=?", MID)}

# 1. the phone timer page defines its helpers before the page script first calls them
html = c.get(f"/phone/race/{RID}").get_data(as_text=True)
assert 0 < html.index("async function jget") < html.index("\nload();"), "helpers must come first"
print("PASS 1: the phone timer's first load no longer fails (helpers are defined before it runs)")

# 2. the timer QR keeps a signed-in coach signed in; a helper with no login still gets the timer session
ex("UPDATE meets SET timer_token='tt-live' WHERE id=?", MID)
r = c.get("/t/tt-live")
assert r.status_code == 302 and r.headers["Location"].endswith("/phone") and "Set-Cookie" not in r.headers
assert c.get("/meets").status_code == 200 and "Create a meet" in c.get("/meets").get_data(as_text=True)
anon = client()
r = anon.get("/t/tt-live")
assert r.status_code == 302 and auth.SESSION_COOKIE in r.headers.get("Set-Cookie", "")
assert anon.get(f"/phone/race/{RID}").status_code == 200 and anon.get("/meets").status_code != 200
other = ex("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)",
           ex("INSERT INTO districts (name, slug) VALUES ('Else','else')"), "x@else.example", "X", "coach")
r = client(other).get("/t/tt-live")                # signed in, but cannot time THIS meet: timer session as before
assert auth.SESSION_COOKIE in r.headers.get("Set-Cookie", "")
print("PASS 2: scanning the timer QR while signed in no longer replaces the coach's login")

# 6. bib entry says what happened to a duplicate or an unknown bib (still never blocks)
assert c.post(f"/races/{RID}/start", json={}, headers=H).status_code == 200
j = c.post(f"/races/{RID}/finish", json={"bib": BIB[ATH[0]]}, headers=H).get_json()
assert j["ok"] and j["name"] == "Runner 1" and not j.get("note") and not j.get("duplicate")
j = c.post(f"/races/{RID}/finish", json={"bib": BIB[ATH[0]]}, headers=H).get_json()
assert j["duplicate"] and j["name"] == "Runner 1" and j["place"] == 1
assert len(q("SELECT 1 FROM finishers WHERE race_id=?", RID)) == 1
j = c.post(f"/races/{RID}/finish", json={"bib": 99}, headers=H).get_json()
assert j["ok"] and "isn't in this meet" in j["note"] and j["name"] is None                 # saved, with a note
fid = q("SELECT id FROM finishers WHERE race_id=? AND bib=99", RID)[0][0]
j = c.post(f"/finishers/{fid}/bib", json={"bib": 98}, headers=H).get_json()
assert "isn't in this meet" in j["note"]
j = c.post(f"/finishers/{fid}/bib", json={"bib": BIB[ATH[1]]}, headers=H).get_json()
assert j["ok"] and not j["note"]
console = c.get(f"/races/{RID}/console").get_data(as_text=True)
assert 'id="bibmsg"' in console and "is already in" in console and "Not added again" in console
print("PASS 6: a duplicate or unknown bib is reported on the console instead of being swallowed")

# 3 + 5 (fun runs). Two hosts on the self-serve organizer.
WEB = ex("INSERT INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')")
def host(email):
    return ex("INSERT INTO users (organizer_id,email,name,role) VALUES (?,?,?,?)", WEB, email, email, "race_director")
def event(uid, email, name):
    mid = ex("INSERT INTO meets (organizer_id,sport,name,date,public_token,team_scoring,settings_json) VALUES (?,?,?,?,?,0,?)",
             WEB, "road", name, "2027-05-01", name, json.dumps({"host_paid": False, "owner_user_id": uid, "owner_email": email}))
    ex("INSERT INTO races (meet_id, name, capture_mode) VALUES (?, '5K', 'tapselect')", mid)
    return mid
settings = lambda mid: json.loads(q("SELECT settings_json FROM meets WHERE id=?", mid)[0][0])   # noqa: E731
redemptions = lambda: len(q("SELECT 1 FROM promo_redemptions WHERE code='HALF'"))               # noqa: E731
A = host("a@example.com"); A1 = event(A, "a@example.com", "A1"); A2 = event(A, "a@example.com", "A2")
wa1, wa2 = client(A, "event_owner", A1), client(A, "event_owner", A2)

day = wa1.get(f"/meets/{A1}/xc-day").get_data(as_text=True)
assert 'href="/events">← Events' in day and 'href="/meets">← Meets' not in day
assert 'href="/meets">← Meets' in c.get(f"/meets/{MID}/xc-day").get_data(as_text=True)        # schools unchanged
print("PASS 3: a fun-run host's Race day page links back to Events, not the school Meets list")

before = used("HALF")
assert "Go live — $100.00 per event" in wa1.get(f"/meets/{A1}").get_data(as_text=True)
r = wa1.post(f"/meets/{A1}/host-redeem", json={"code": "half"}, headers=H)
assert r.get_json()["url"] and LINKS[-1]["amount"] == 5000 and "50% off" in LINKS[-1]["name"]
assert used("HALF") == before and redemptions() == 0, "applying is not using"
page = wa1.get(f"/meets/{A1}").get_data(as_text=True)                  # they backed out of Square
assert "$50.00 with code HALF" in page and "Pay $50.00 with Square" in page and "instead of $100.00" in page
wa1.post(f"/meets/{A1}/host-pay-square", json={}, headers=H)           # the plain Pay button keeps the discount
assert LINKS[-1]["amount"] == 5000
# they abandon that event and start another: the first-event code still works there
r = wa2.post(f"/meets/{A2}/host-redeem", json={"code": "HALF"}, headers=H)
assert r.status_code == 200 and LINKS[-1]["amount"] == 5000 and used("HALF") == before
OK_ORDERS.add("ord-a2")
assert wa2.get(f"/meets/{A2}/host-square-return?orderId=ord-a2").headers["Location"].endswith("?paid=1")
s2 = settings(A2)
assert s2["host_paid"] and s2["promo_code"] == "HALF" and s2["promo_pct"] == 50 and "promo_pending" not in s2
assert used("HALF") == before + 1 and redemptions() == 1, "counted once, when paid"
road._mark_host_paid(A2, "ord-a2")                                     # the webhook lands too: still once
assert used("HALF") == before + 1 and redemptions() == 1
# now the first event is no longer a first event: full price, and the code is refused there
page = wa1.get(f"/meets/{A1}").get_data(as_text=True)
assert "Go live — $100.00 per event" in page and "with code HALF" not in page
wa1.post(f"/meets/{A1}/host-pay-square", json={}, headers=H)
assert LINKS[-1]["amount"] == 10000
r = wa1.post(f"/meets/{A1}/host-redeem", json={"code": "HALF"}, headers=H)
assert r.status_code == 400 and "first event only" in r.get_json()["error"]
# a free code still publishes at once and is counted at once
B = host("b@example.com"); B1 = event(B, "b@example.com", "B1")
assert client(B, "event_owner", B1).post(f"/meets/{B1}/host-redeem", json={"code": "FREE"}, headers=H).get_json()["paid"]
assert settings(B1)["host_paid"] and used("FREE") == 2

# 5 (school meets): same rule
r = c.post("/meets", data=dict(name="Second Meet", sport="xc", date="2027-09-08", school_ids=[SID]), headers=H)
M2 = int(r.headers["Location"].rsplit("/", 1)[1])
u0, n0 = used("HALF"), redemptions()
assert c.post(f"/meets/{M2}/meet-fee/redeem", json={"code": "HALF"}, headers=H).get_json()["url"]
assert LINKS[-1]["amount"] == 5000 and used("HALF") == u0 and redemptions() == n0
page = c.get(f"/meets/{M2}").get_data(as_text=True)
assert "Go live: $50 for this meet" in page and "code HALF applied, regular $100" in page and "Pay $50 with Square" in page
c.post(f"/meets/{M2}/meet-fee/pay", json={}, headers=H)
assert LINKS[-1]["amount"] == 5000
ORDERS["ord-m2"] = {"note": f"{billing.NOTE_TAG}={M2}", "amount": 5000}
assert "Payment+received" in c.get(f"/meets/{M2}/meet-fee/return?orderId=ord-m2").headers["Location"]
fee = settings(M2)["meet_fee"]
assert fee["paid"] and fee["how"] == "square" and fee["code"] == "HALF" and "meet_fee_promo" not in settings(M2)
assert used("HALF") == u0 + 1 and redemptions() == n0 + 1
assert q("SELECT email FROM promo_redemptions WHERE code='HALF' ORDER BY id DESC")[0][0] == f"school:{SID}"
billing.handle_webhook_order("ord-m2")
assert used("HALF") == u0 + 1 and redemptions() == n0 + 1               # the webhook does not count it twice
print("PASS 5: a half-price code is counted when paid, survives backing out, and the page shows the real price")

# 4. a photo of a paper roster is read (the model call is stubbed; the coach still reviews the rows)
from PIL import Image                                                  # noqa: E402
buf = io.BytesIO(); Image.new("RGB", (3000, 1800), "white").save(buf, "PNG")
SEEN = []
def _vision(system, prompt, image_bytes, media_type="image/jpeg", **kw):
    SEEN.append((system, media_type, Image.open(io.BytesIO(image_bytes)).size))
    return "Name\tGrade\tGender\nAda Runner\t8\tF\nBen Sprinter\t7\tM"
ai.claude_vision = _vision
text = ai.extract_text("Sign Up Sheet.JPG", buf.getvalue())
assert "Ada Runner\t8\tF" in text and SEEN[0][1] == "image/jpeg" and max(SEEN[0][2]) <= 2200
assert "EVERY row" in SEEN[0][0] and "[illegible]" in SEEN[0][0]
for name, data in (("roster.heic", b"x"), ("roster.png", b"not an image")):
    try:
        ai.extract_text(name, data); raise SystemExit("should have refused " + name)
    except ai.RosterParseError:
        pass
ai.normalize_roster = lambda t: [{"name": ln.split("\t")[0], "grade": 8, "gender": "F"} for ln in t.split("\n")[1:]]
r = c.post(f"/schools/{SID}/import/parse", data={"file": (io.BytesIO(buf.getvalue()), "roster.png")},
           headers=H, content_type="multipart/form-data")
assert r.status_code == 200 and [a["name"] for a in r.get_json()["athletes"]] == ["Ada Runner", "Ben Sprinter"]
r = c.post(f"/schools/{SID}/import/parse", data={"file": (io.BytesIO(b"x"), "roster.heic")},
           headers=H, content_type="multipart/form-data")
assert r.status_code == 400 and "JPEG" in r.get_json()["error"]
roster = c.get(f"/schools/{SID}").get_data(as_text=True)
assert ".jpg,.jpeg,.png" in roster and "a photo of a paper list" in roster
print("PASS 4: roster import accepts a photo, as the home page says it does")

# 7. an unreadable track time is reported and does not wipe the mark that was there
r = c.post("/meets", data=dict(name="Track Meet", sport="track", date="2027-04-01", school_ids=[SID]), headers=H)
TM = int(r.headers["Location"].rsplit("/", 1)[1])
assert c.post(f"/meets/{TM}/meet-fee/redeem", json={"code": "FREE"}, headers=H).get_json()["paid"]
ev = q("SELECT id FROM events WHERE name='100m'")[0][0]
ME = ex("INSERT INTO meet_events (meet_id, event_id, gender) VALUES (?,?,'M')", TM, ev)
E = [ex("INSERT INTO entries (meet_event_id, runner_id, school_id) VALUES (?,?,?)", ME, a, SID) for a in ATH]
r = c.post(f"/meet-events/{ME}/marks", data={f"mark_{E[0]}": "13.4", f"mark_{E[1]}": "12.9", f"mark_{E[2]}": ""}, headers=H)
assert r.status_code == 302 and "bad=" not in r.headers["Location"]
mark = lambda e: q("SELECT mark_seconds, place FROM results WHERE entry_id=?", e)                # noqa: E731
assert mark(E[0])[0]["mark_seconds"] == 13.4 and mark(E[1])[0]["place"] == 1
r = c.post(f"/meet-events/{ME}/marks", data={f"mark_{E[0]}": "abc", f"mark_{E[1]}": "12.8", f"mark_{E[2]}": "1:02.5"}, headers=H)
loc = r.headers["Location"]
assert "bad=" in loc and "abc" in loc, loc
assert mark(E[0])[0]["mark_seconds"] == 13.4, "the earlier 13.4 must survive a typo"
assert mark(E[1])[0]["mark_seconds"] == 12.8 and mark(E[2])[0]["mark_seconds"] == 62.5           # the rest saved
page = c.get(loc).get_data(as_text=True)
assert "Not saved, because I could not read" in page and "Runner 1: abc" in page and "Everything else was saved" in page
assert "Not saved" not in c.get(f"/meet-events/{ME}").get_data(as_text=True)
print("PASS 7: an unreadable track time is named on the page and the earlier mark is kept")

# 8. meets held before the change keep the team scores they were announced with
from xctimerpkg import xc                                              # noqa: E402
order = ["A"] * 7 + ["B"] + ["A", "A"] + ["B"] * 4
def meet_with(date):
    mid = ex("INSERT INTO meets (district_id, sport, name, date, public_token, team_scoring) VALUES (?,?,?,?,?,1)",
             DID, "xc", "Dated " + str(date), date, "tok" + str(date))
    rid = ex("INSERT INTO races (meet_id, name, capture_mode) VALUES (?, 'Boys', 'tapselect')", mid)
    for i, s_ in enumerate(order):
        ex("INSERT INTO finishers (race_id, seq, bib, elapsed_seconds, snap_name, snap_grade, snap_gender, snap_school) "
           "VALUES (?,?,?,?,?,8,'M',?)", rid, i + 1, 500 + i, 600.0 + i, f"R{i}", s_)
    return mid
def b_score(mid):
    by_race = {t["school"]: t["score"] for g_ in xc.build_results(mid).values() if isinstance(g_, dict)
               for t in (g_.get("teams") or [])}
    by_grade = {t["school"]: t["score"] for _l, teams, _n in xc._team_grade_gender_groups(mid) for t in teams}
    return by_race.get("B"), by_grade.get("B")
assert xc.FIRST_SEVEN_FROM == "2026-11-13"
assert b_score(meet_with("2026-10-07")) == (58, 58)        # last season: as announced
assert b_score(meet_with("2026-11-12")) == (58, 58)
assert b_score(meet_with("2026-11-13")) == (50, 50)        # from the change on: first seven
assert b_score(meet_with("2027-09-01")) == (50, 50)
assert b_score(meet_with(None)) == (50, 50)                # undated: the current rule
print("PASS 8: meets before 2026-11-13 keep their announced team scores; later meets use first seven")
# 9. race day and the phone heat list name the capture mode in words, never the stored key
ex("UPDATE races SET capture_mode='tapselect' WHERE id=?", RID)
day = client(COACH).get(f"/meets/{MID}/xc-day").get_data(as_text=True)
assert "Tap → scan or select" in day and ">tapselect<" not in day
ph = client(COACH).get("/phone").get_data(as_text=True)
assert "· Tap → scan or select" in ph and "· tapselect" not in ph
print("PASS 9: capture modes read as words on race day and in the phone heat list")
print("ALL PASS")
