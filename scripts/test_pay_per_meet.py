#!/usr/bin/env python3
"""District plan tag + pay-per-meet go-live gate + coaches creating meets (1.112.0).
    python scripts/test_pay_per_meet.py
Uses a temp DB (XCTIMER_DB) and a fake Square; never touches real data or the network."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

import xctimerpkg                                                      # noqa: E402
sys.modules["xctimer"] = xctimerpkg      # raceday.py imports the package by its server name
from xctimerpkg import app as appmod, db, auth, billing, square, raceday   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}

# ---- fake Square ------------------------------------------------------------
LINKS, ORDERS = [], {}
square.is_configured = lambda: True
def _link(name, amount_cents, redirect_url, note):
    LINKS.append(dict(name=name, amount=amount_cents, redirect=redirect_url, note=note))
    return "https://square.link/u/fake"
square.create_payment_link = _link
square.completed_order = lambda oid: ORDERS.get(oid)

# ---- fixtures ---------------------------------------------------------------
c = db.connect()
def district(name):
    did = c.execute("INSERT INTO districts (name, slug) VALUES (?,?)", (name, name.lower())).lastrowid
    sids = []
    for n in ("North", "South"):
        sid = c.execute("INSERT INTO schools (district_id, name) VALUES (?,?)", (did, f"{name} {n}")).lastrowid
        for i in range(3):
            c.execute("INSERT INTO athletes (school_id, name, grade, gender, does_xc, does_track, active) "
                      "VALUES (?,?,8,'F',1,1,1)", (sid, f"{name}{n} Runner{i}"))
        sids.append(sid)
    return did, sids
def user(did, email, role, school=None, demo=0):
    uid = c.execute("INSERT INTO users (district_id, email, name, role, is_demo) VALUES (?,?,?,?,?)",
                    (did, email, email.split("@")[0], role, demo)).lastrowid
    if school:
        c.execute("INSERT INTO user_schools (user_id, school_id) VALUES (?,?)", (uid, school))
    return uid
PAY, (PN, PS) = district("Payper")
SUB, (SN, SS) = district("Subs")
U = dict(super=user(None, "root@x.example", "super_admin"),
         padmin=user(PAY, "admin@payper.example", "district_admin"),
         pcoach=user(PAY, "coach.north@payper.example", "coach", PN),
         pcoach2=user(PAY, "coach.south@payper.example", "coach", PS),
         pdemo=user(PAY, "demo@payper.example", "district_admin", demo=1),
         sadmin=user(SUB, "admin@subs.example", "district_admin"),
         scoach=user(SUB, "coach@subs.example", "coach", SN))
c.commit(); c.close()


def client(who):
    w = application.test_client()
    w.set_cookie(auth.SESSION_COOKIE, auth.create_session(U[who]))
    w.set_cookie("csrftoken", "x")
    return w


def q(sql, *a):
    conn = db.connect()
    rows = conn.execute(sql, a).fetchall()
    conn.close()
    return rows


def new_meet(w, **form):
    data = dict(name="Meet", sport="xc", date="2026-09-01")
    data.update(form)
    r = w.post("/meets", data=data, headers=H)
    assert r.status_code == 302, (r.status_code, form)
    return int(r.headers["Location"].rsplit("/", 1)[1])


def first_race(mid):
    return q("SELECT id FROM races WHERE meet_id=? ORDER BY id", mid)[0][0]


def can_time(w, mid):
    r = w.get(f"/races/{first_race(mid)}/eligible")
    return r.status_code == 200


sup, padmin, pcoach, pcoach2 = client("super"), client("padmin"), client("pcoach"), client("pcoach2")
sadmin, scoach = client("sadmin"), client("scoach")

# 1. no plan stored == subscription: nothing changes for an untouched district
assert billing.district_plan(PAY) == billing.district_plan(SUB) == "subscription"
old = new_meet(padmin, name="Before The Switch", host_school_id=PN, school_ids=[PN, PS])
assert can_time(padmin, old)
html = padmin.get(f"/meets/{old}").get_data(as_text=True)
assert "Go live" not in html and "timer-qr.png" in html
print("PASS 1: a district with no plan tag behaves as a subscription district (every meet live)")

# 2. the tag is Super Admin only and shows on the Districts page
assert padmin.post(f"/districts/{PAY}/plan", data={"plan": "per_meet"}, headers=H).status_code == 403
assert sup.post(f"/districts/{PAY}/plan", data={"plan": "nonsense"}, headers=H).status_code == 400
assert sup.post(f"/districts/{PAY}/plan", data={"plan": "per_meet"}, headers=H).status_code == 302
assert billing.district_plan(PAY) == "per_meet" and billing.district_plan(SUB) == "subscription"
page = sup.get("/districts").get_data(as_text=True)
assert "<th>Plan</th>" in page and "Pay per meet</span>" in page and "Paid subscription</span>" in page
sup.post("/districts", data={"name": "Brand New", "plan": "per_meet"}, headers=H)
sup.post("/districts", data={"name": "Brand Sub"}, headers=H)
plans = {r["name"]: billing.plan_of(r["settings_json"]) for r in q("SELECT * FROM districts")}
assert plans["Brand New"] == "per_meet" and plans["Brand Sub"] == "subscription"
print("PASS 2: Super Admin sets the plan tag per district; others cannot")

# 3. meets that existed before the switch stay live (marked included)
assert can_time(padmin, old)
assert json.loads(q("SELECT settings_json FROM meets WHERE id=?", old)[0][0])["meet_fee"]["how"] == "included"
print("PASS 3: switching a district to pay per meet never locks a meet it already had")

# 4. coaches create meets, hosted at their own school
mid = new_meet(pcoach, name="North Invite", sport="track", host_school_id=PS, school_ids=[PS],
               championship="1")
m = q("SELECT * FROM meets WHERE id=?", mid)[0]
assert m["host_school_id"] == PN, "host is forced to the coach's own school"
assert {r[0] for r in q("SELECT school_id FROM meet_schools WHERE meet_id=?", mid)} == {PN, PS}
assert not m["championship"] and not m["time_trial"] and m["sport"] == "track"
assert pcoach.post("/meets", data=dict(name="R", sport="road", date="2026-09-01"), headers=H).status_code == 302
assert q("SELECT sport FROM meets ORDER BY id DESC LIMIT 1")[0][0] == "xc"       # road is not a coach option
form = pcoach.get("/meets").get_data(as_text=True)
assert "Create a meet" in form and "Payper North</b>" in form and "$100 per meet" in form
assert "Championship" not in form and "North Invite" in form and "Not live yet" in form
assert "$100" not in scoach.get("/meets").get_data(as_text=True)                  # subscription district
xcm = new_meet(pcoach, name="North XC Invite", school_ids=[PN, PS])
print("PASS 4: a coach can create a full meet (host = their school); no championship or road")

# 5. the new meet is built freely but cannot go live
setup = pcoach.get(f"/meets/{xcm}").get_data(as_text=True)
assert "Go live: $100 for this meet" in setup and "Pay $100 with Square" in setup
assert "timer-qr.png" not in setup and "mark as covered" not in setup
assert pcoach.post(f"/meets/{xcm}/lock-bibs", data={"lock": "1"}, headers=H).status_code in (200, 302)
assert pcoach.get(f"/meets/{xcm}/stickers.pdf").status_code == 200                # printing still works
rid = first_race(xcm)
r = pcoach.post(f"/races/{rid}/start", json={}, headers=H)
assert r.status_code == 403 and r.get_json()["locked"] and "isn't live yet" in r.get_json()["error"]
assert q("SELECT start_time FROM races WHERE id=?", rid)[0][0] is None
r = pcoach.get(f"/phone/race/{rid}")
assert r.status_code == 302 and f"/meets/{xcm}?err=" in r.headers["Location"]
assert "Go live" in pcoach.get(f"/meets/{xcm}/xc-day").get_data(as_text=True)
assert "North XC Invite" not in pcoach.get("/phone").get_data(as_text=True)
conn = db.connect(); conn.execute("UPDATE meets SET timer_token='locktok' WHERE id=?", (xcm,)); conn.commit(); conn.close()
r = application.test_client().get("/t/locktok")
assert r.status_code == 403 and b"live yet" in r.data and b"Timing opens once" in r.data, (r.status_code, r.data[-400:])
# the attending school's coach sees why, with no pay button; a demo admin cannot pay
other = pcoach2.get(f"/meets/{xcm}").get_data(as_text=True)
assert "isn’t live yet" in other and "Pay $100" not in other
assert pcoach2.post(f"/meets/{xcm}/meet-fee/pay", json={}, headers=H).status_code == 403
demo = client("pdemo")
assert "Pay $100" not in demo.get(f"/meets/{xcm}").get_data(as_text=True)
assert demo.post(f"/meets/{xcm}/meet-fee/pay", json={}, headers=H).status_code == 403
# the track meet is locked the same way
me_page = pcoach.get(f"/meets/{mid}/meet-day").get_data(as_text=True)
assert "Go live" in me_page
# the race-day morning email skips a meet that is not live
conn = db.connect()
todays = {m["id"] for m in raceday.todays_meets(conn, "2026-09-01")}
conn.close()
assert old in todays and xcm not in todays
print("PASS 5: an unpaid meet can be set up and printed, but timing, the phone link and the "
      "race-day email stay off")

# 6. practice time trials are never charged
tt = new_meet(pcoach, name="Tuesday TT", time_trial="1")
assert can_time(pcoach, tt) and "Go live" not in pcoach.get(f"/meets/{tt}").get_data(as_text=True)
print("PASS 6: a practice time trial is live without a fee")

# 7. the road-event shortcuts do not unlock a school meet
pcoach.post(f"/meets/{xcm}/host-publish", headers=H)
assert not can_time(pcoach, xcm)
print("PASS 7: the fun-run publish route cannot take a school meet live")

# 8. Square checkout: $100, bound to this meet, verified before it goes live
r = pcoach.post(f"/meets/{xcm}/meet-fee/pay", json={}, headers=H)
assert r.get_json()["url"] == "https://square.link/u/fake"
assert LINKS[-1]["amount"] == 10000 and LINKS[-1]["note"] == f"xctimer_schoolmeet={xcm}"
assert LINKS[-1]["redirect"].endswith(f"/meets/{xcm}/meet-fee/return")
ORDERS.update({
    "other-meet": {"note": f"xctimer_schoolmeet={xcm}7", "amount": 10000},     # id that merely starts the same
    "road-order": {"note": f"xctimer_meet={xcm}", "amount": 10000},             # a fun-run payment
    "too-little": {"note": f"xctimer_schoolmeet={xcm}", "amount": 5000},
    "good": {"note": f"xctimer_schoolmeet={xcm}", "amount": 10000},
})
for bad in ("", "missing", "other-meet", "road-order", "too-little"):
    r = pcoach.get(f"/meets/{xcm}/meet-fee/return?orderId={bad}")
    assert r.status_code == 302 and "err=" in r.headers["Location"], bad
    assert not can_time(pcoach, xcm), bad
assert pcoach2.get(f"/meets/{xcm}/meet-fee/return?orderId=good").status_code == 403
r = pcoach.get(f"/meets/{xcm}/meet-fee/return?orderId=good")
assert r.status_code == 302 and "msg=" in r.headers["Location"]
assert can_time(pcoach, xcm) and can_time(pcoach2, xcm)                           # attending coach can time too
live = pcoach.get(f"/meets/{xcm}").get_data(as_text=True)
assert "Go live" not in live and "timer-qr.png" in live
assert pcoach.post(f"/races/{rid}/start", json={}, headers=H).status_code == 200
assert application.test_client().get("/t/locktok").status_code == 302
assert "Not live yet" not in pcoach.get("/meets").get_data(as_text=True).split("North XC Invite")[1].split("</tr>")[0]
print("PASS 8: paying through Square takes the meet live; wrong, underpaid or borrowed orders do not")

# 9. the webhook takes a meet live even if the payer never returns
ORDERS["hook"] = {"note": f"xctimer_schoolmeet={mid}", "amount": 10000}
with application.app_context():
    assert not billing.handle_webhook_order("too-little-x") and billing.handle_webhook_order("hook")
st = json.loads(q("SELECT settings_json FROM meets WHERE id=?", mid)[0][0])["meet_fee"]
assert st["paid"] and st["how"] == "square" and st["order_id"] == "hook"
print("PASS 9: the Square webhook marks the meet paid")

# 10. Super Admin can cover a meet, or put the fee back
free = new_meet(padmin, name="First One Free", host_school_id=PS, school_ids=[PN, PS])
assert not can_time(padmin, free)
assert padmin.post(f"/meets/{free}/meet-fee/comp", data={"on": "1"}, headers=H).status_code == 403
assert "mark as covered" in sup.get(f"/meets/{free}").get_data(as_text=True)
sup.post(f"/meets/{free}/meet-fee/comp", data={"on": "1"}, headers=H)
assert can_time(padmin, free)
assert "Require payment" in sup.get(f"/meets/{free}").get_data(as_text=True)
assert "Require payment" not in padmin.get(f"/meets/{free}").get_data(as_text=True)
sup.post(f"/meets/{free}/meet-fee/comp", data={"on": "0"}, headers=H)
assert not can_time(padmin, free)
# moving the district back to a subscription opens everything again
sup.post(f"/districts/{PAY}/plan", data={"plan": "subscription"}, headers=H)
assert can_time(padmin, free)
sup.post(f"/districts/{PAY}/plan", data={"plan": "per_meet"}, headers=H)
assert can_time(padmin, free), "meets that exist at the switch are included"
print("PASS 10: Super Admin can mark a meet as covered or require the fee; a subscription unlocks all")

# 11. a coach may delete the meet they created, not one the district made at their school
assert pcoach2.post(f"/meets/{xcm}/delete", headers=H).status_code == 403
assert pcoach.post(f"/meets/{old}/delete", headers=H).status_code == 403        # admin-made, hosted at North
assert pcoach.post(f"/meets/{xcm}/delete", headers=H).status_code == 302
assert not q("SELECT 1 FROM meets WHERE id=?", xcm) and q("SELECT 1 FROM meets WHERE id=?", old)
print("PASS 11: a coach can delete only the meets they created")

# 12. subscription district: coaches create meets and they are live at once
sm = new_meet(scoach, name="Subs Dual", school_ids=[SN, SS])
assert can_time(scoach, sm) and "Go live" not in scoach.get(f"/meets/{sm}").get_data(as_text=True)
print("PASS 12: in a subscription district a coach's meet is live immediately")

# 13. promo codes: everything is $100 unless they have a code
from xctimerpkg import road                                                        # noqa: E402
assert road.HOST_FEE_CENTS == billing.MEET_FEE_CENTS == 10000
conn = db.connect()
for code, pct, first, mx in (("FREE100", 100, 0, None), ("HALF", 50, 0, None),
                             ("FIRST", 100, 1, None), ("ONCE", 100, 0, 1)):
    conn.execute("INSERT INTO promo_codes (code, active, percent_off, first_event_only, max_uses, used_count) "
                 "VALUES (?,1,?,?,?,0)", (code, pct, first, mx))
conn.commit(); conn.close()


def redeem(w, mid, code):
    return w.post(f"/meets/{mid}/meet-fee/redeem", json={"code": code}, headers=H)


a = new_meet(pcoach, name="Code A", school_ids=[PN, PS])
assert "Promo code" in pcoach.get(f"/meets/{a}").get_data(as_text=True)
assert redeem(pcoach, a, "nope").status_code == 400 and redeem(pcoach, a, "").status_code == 400
assert redeem(pcoach2, a, "FREE100").status_code == 403 and redeem(client("pdemo"), a, "FREE100").status_code == 403
assert not can_time(pcoach, a)
r = redeem(pcoach, a, "half")                                                     # partial: Square for the rest
assert r.get_json()["url"] and LINKS[-1]["amount"] == 5000 and LINKS[-1]["note"] == f"xctimer_schoolmeet={a}"
assert "Pay $50 with Square" in pcoach.get(f"/meets/{a}").get_data(as_text=True)
ORDERS["a-short"] = {"note": f"xctimer_schoolmeet={a}", "amount": 4000}
ORDERS["a-half"] = {"note": f"xctimer_schoolmeet={a}", "amount": 5000}
pcoach.get(f"/meets/{a}/meet-fee/return?orderId=a-short"); assert not can_time(pcoach, a)
pcoach.get(f"/meets/{a}/meet-fee/return?orderId=a-half"); assert can_time(pcoach, a)
b = new_meet(pcoach, name="Code B", school_ids=[PN])
ORDERS["b-half"] = {"note": f"xctimer_schoolmeet={b}", "amount": 5000}             # no code applied here
pcoach.get(f"/meets/{b}/meet-fee/return?orderId=b-half"); assert not can_time(pcoach, b)
assert redeem(pcoach, b, "FIRST").get_json()["paid"] and can_time(pcoach, b)       # 100%: live, no card
st = json.loads(q("SELECT settings_json FROM meets WHERE id=?", b)[0][0])["meet_fee"]
assert st["how"] == "promo" and st["code"] == "FIRST"
cc = new_meet(pcoach, name="Code C", school_ids=[PN])
r = redeem(pcoach, cc, "FIRST")                                                    # same host school, second meet
assert r.status_code == 400 and "first meet" in r.get_json()["error"] and not can_time(pcoach, cc)
assert q("SELECT used_count FROM promo_codes WHERE code='FIRST'")[0][0] == 1       # the refusal burned no use
d = new_meet(pcoach2, name="Code D", school_ids=[PS])
assert redeem(pcoach2, d, "FIRST").get_json()["paid"]                              # another school's first meet
assert redeem(pcoach, cc, "ONCE").get_json()["paid"] and can_time(pcoach, cc)
e = new_meet(pcoach, name="Code E", school_ids=[PN])
assert redeem(pcoach, e, "ONCE").status_code == 400 and not can_time(pcoach, e)    # used up
print("PASS 13: promo codes take a school meet live (free, or by card for the reduced amount); "
      "first-meet codes work once per host school")

# 14. pricing has its own public page, linked from the marketing page; both match the app
import re                                                                          # noqa: E402
anon = application.test_client()
home = anon.get("/welcome").get_data(as_text=True)
assert home.count('href="/pricing"') == 2 and 'id="pricing"' not in home and '<div class="amt">' not in home
r = anon.get("/pricing"); page = r.get_data(as_text=True)
assert r.status_code == 200 and "<title>Pricing — XCTimer</title>" in page and not re.search(r"\$50(?!0)", page)
assert page.count('<div class="amt">$100<span>') == 3 and billing.fee_str() == "$100" == road._fee_whole(road.HOST_FEE_CENTS)
assert pcoach.get("/pricing").status_code == 200                                   # signed in or not
host = anon.get("/host").get_data(as_text=True)
assert "then $100 per event" in host and "$50" not in host
print("PASS 14: /pricing is public and linked from the marketing page; every page says $100")
print("ALL PASS")
