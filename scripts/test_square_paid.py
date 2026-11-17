#!/usr/bin/env python3
"""Square's "is this order paid?" check, against orders shaped the way Square really returns
them for a payment link (1.135.3).
    python scripts/test_square_paid.py
A paid payment-link order stays OPEN with a null note; the meet tag is on the payment. The
first real card payment (2026-11-17) was turned away because the check wanted a COMPLETED
order with the tag in the order's note. No network: square._request is stubbed. Exit 0 on success."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.environ["SQUARE_LOCATION_ID"] = "LOC1"
os.environ["SQUARE_ACCESS_TOKEN"] = "test-token"
os.environ["SQUARE_WEBHOOK_SIGNATURE_KEY"] = "whkey"
os.environ["XC_PUBLIC_URL"] = "https://example.test"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

import base64, hashlib, hmac, json                                    # noqa: E402
from xctimerpkg import app as appmod, db, square, billing             # noqa: E402

ORDERS, PAYMENTS, CALLS = {}, {}, []


def fake_request(method, path, payload=None):
    CALLS.append((method, path))
    assert method == "GET", (method, path)
    kind, _, oid = path.rpartition("/")
    if kind == "/v2/orders" and oid in ORDERS:
        return {"order": ORDERS[oid]}
    if kind == "/v2/payments" and oid in PAYMENTS:
        return {"payment": PAYMENTS[oid]}
    raise RuntimeError("404 " + path)


square._request = fake_request


def money(c):
    return {"amount": c, "currency": "USD"}


def order(oid, total, state="OPEN", note=None, pays=(), loc="LOC1"):
    """pays: (payment id, cents, status, note[, refunded cents])."""
    ORDERS[oid] = {"id": oid, "state": state, "location_id": loc, "note": note, "total_money": money(total),
                   "tenders": [{"id": p[0], "payment_id": p[0], "type": "CARD", "amount_money": money(p[1])}
                               for p in pays]}
    for p in pays:
        PAYMENTS[p[0]] = {"id": p[0], "status": p[2], "note": p[3], "order_id": oid, "total_money": money(p[1]),
                          "refunded_money": money(p[4]) if len(p) > 4 else None}
    return oid


# --- 1. the real shape: paid, order still OPEN, tag on the payment
o1 = order("o1", 2400, pays=[("p1", 2400, "COMPLETED", "xctimer_schoolmeet=31")])
assert square.paid_order("o1") == {"note": "xctimer_schoolmeet=31", "amount": 2400}
assert square.completed_order("o1") == {"note": "xctimer_schoolmeet=31", "amount": 2400}
assert square.order_ok("o1") and square.order_ok("o1", expect_note_substr="xctimer_schoolmeet=31")
assert not square.order_ok("o1", expect_note_substr="xctimer_schoolmeet=3"), "meet 3 must not match meet 31"
o2 = order("o2", 10000, pays=[("p2", 10000, "COMPLETED", "xctimer_meet=26")])
assert square.order_meet_id("o2") == 26 and square.order_ok("o2", expect_note_substr="xctimer_meet=26")
assert not square.order_ok("o2", expect_note_substr="xctimer_meet=2")
assert square.order_meet_id("o1") is None, "a school-meet order is not a fun-run order"
print("PASS 1: a paid payment-link order (OPEN, tag on the payment) counts as paid")

# --- 2. not paid
assert square.paid_order("") is None and square.paid_order(None) is None
assert square.paid_order("nope") is None, "unknown order (Square 404)"
assert square.paid_order(order("o3", 5000, state="DRAFT")) is None, "link made, never paid"
assert square.paid_order(order("o4", 5000)) is None, "open, no payment"
assert square.paid_order(order("o5", 5000, pays=[("p5", 5000, "FAILED", "xctimer_meet=5")])) is None
assert square.paid_order(order("o6", 5000, pays=[("p6", 5000, "APPROVED", "xctimer_meet=6")])) is None, \
    "authorized but not captured"
assert square.paid_order(order("o7", 5000, pays=[("p7", 2000, "COMPLETED", "xctimer_meet=7")])) is None, "part paid"
assert square.paid_order(order("o8", 5000, pays=[("p8", 5000, "COMPLETED", "xctimer_meet=8", 5000)])) is None, \
    "refunded"
assert square.paid_order(order("o9", 5000, state="CANCELED", pays=[("p9", 5000, "COMPLETED", "xctimer_meet=9")])) is None
assert square.paid_order(order("o10", 5000, loc="OTHER", pays=[("p10", 5000, "COMPLETED", "xctimer_meet=10")])) is None, \
    "another app's location on the shared Square account"
order("o11", 5000, pays=[("p11", 5000, "COMPLETED", "xctimer_meet=11")])
PAYMENTS["p11"]["order_id"] = "someone-elses-order"
assert square.paid_order("o11") is None, "a payment that belongs to a different order"
assert not square.order_ok("o4") and square.order_meet_id("o4") is None and square.completed_order("o4") is None
print("PASS 2: unpaid, part-paid, refunded, canceled and foreign orders are all refused")

# --- 3. other shapes that are paid
o12 = order("o12", 5000, state="COMPLETED", note="xctimer_meet=12", pays=[("p12", 5000, "COMPLETED", None)])
assert square.paid_order("o12") == {"note": "xctimer_meet=12", "amount": 5000} and square.order_meet_id("o12") == 12
o13 = order("o13", 5000, pays=[("p13a", 5000, "FAILED", None), ("p13b", 5000, "COMPLETED", "xctimer_meet=13")])
assert square.paid_order("o13") == {"note": "xctimer_meet=13", "amount": 5000}, "a declined card, then a good one"
print("PASS 3: a COMPLETED order with the tag on the order, and a retry after a decline, both count")

# --- 4. end to end: the return page and the webhook both take a school meet live
application = appmod.create_app()
application.config["TESTING"] = True
web = application.test_client()


def ex(sql, *a):
    c = db.connect()
    rid = c.execute(sql, a).lastrowid
    c.commit(); c.close()
    return rid


DID = ex("INSERT INTO districts (name, slug, settings_json) VALUES ('D','d',?)", json.dumps({"plan": "per_meet"}))


def meet(name):
    return ex("INSERT INTO meets (district_id, sport, name, date, public_token) VALUES (?,?,?,?,?)",
              DID, "track", name, "2027-04-01", name)


def live(mid):
    c = db.connect()
    m = c.execute("SELECT * FROM meets WHERE id=?", (mid,)).fetchone()
    c.close()
    return billing.meet_live(m), billing.fee_state(m)


def hook(order_id, pay_id):
    body = json.dumps({"type": "payment.updated", "data": {"object": {"payment": {
        "id": pay_id, "status": "COMPLETED", "order_id": order_id}}}}).encode()
    sig = base64.b64encode(hmac.new(b"whkey", b"https://example.test/square/webhook" + body,
                                    hashlib.sha256).digest()).decode()
    return web.post("/square/webhook", data=body, headers={"X-Square-Hmacsha256-Signature": sig,
                                                           "Content-Type": "application/json"})


m1 = meet("hookmeet")
assert live(m1)[0] is False
order("w1", 10000, pays=[("wp1", 10000, "COMPLETED", f"xctimer_schoolmeet={m1}")])
assert hook("w1", "wp1").status_code == 200
ok, st = live(m1)
assert ok and st["how"] == "square" and st["order_id"] == "w1", st
print("PASS 4: the webhook takes a paid school meet live")

m2 = meet("shortmeet")
order("w2", 2400, pays=[("wp2", 2400, "COMPLETED", f"xctimer_schoolmeet={m2}")])
assert hook("w2", "wp2").status_code == 200
assert live(m2)[0] is False, "$24 does not cover a $100 fee with no promo code applied"
c = db.connect()
c.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps({"meet_fee_promo": {"code": "PART76", "pct": 76}}), m2))
c.execute("INSERT INTO promo_codes (code, active, max_uses, used_count, percent_off, first_event_only, created_at) "
          "VALUES ('PART76',1,1,0,76,0,'2026-11-17')")
c.commit(); c.close()
assert hook("w2", "wp2").status_code == 200
ok, st = live(m2)
assert ok and st["how"] == "square" and st["code"] == "PART76" and st["pct"] == 76, st
c = db.connect()
assert c.execute("SELECT used_count FROM promo_codes WHERE code='PART76'").fetchone()[0] == 1
c.close()
assert hook("w2", "wp2").status_code == 200
c = db.connect()
assert c.execute("SELECT used_count FROM promo_codes WHERE code='PART76'").fetchone()[0] == 1, "counted once"
c.close()
m3 = meet("othermeet")
assert hook("w2", "wp2").status_code == 200 and live(m3)[0] is False, "an order pays only the meet it was made for"
bad = web.post("/square/webhook", data=b"{}", headers={"X-Square-Hmacsha256-Signature": "nope"})
assert bad.status_code == 401
print("PASS 5: a discounted payment needs its promo code, uses the code once, and pays only its own meet")
print("ALL PASS")
