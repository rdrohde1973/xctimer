#!/usr/bin/env python3
"""WP-0008: first_event_only promo codes. Run with a Python that has Flask installed:
    python scripts/test_promo_first_event.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import json, os, sys, tempfile, tempfile as _t

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth                     # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True

# Migration idempotency: run again on the existing DB.
db.init_db(); db.init_db()
conn = db.connect()
assert "first_event_only" in [r[1] for r in conn.execute("PRAGMA table_info(promo_codes)")]
web = conn.execute("INSERT INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')").lastrowid
for code, fo in (("ONCE", 1), ("ALWAYS", 0)):
    conn.execute("INSERT INTO promo_codes (code, active, max_uses, used_count, percent_off, first_event_only) "
                 "VALUES (?,1,NULL,0,100,?)", (code, fo))


def host(email):
    uid = conn.execute("INSERT INTO users (organizer_id,email,name,role) VALUES (?,?,?,?)",
                       (web, email, email, "race_director")).lastrowid
    return uid


def event(uid, email, name):
    mid = conn.execute("INSERT INTO meets (organizer_id,sport,name,public_token,team_scoring,settings_json) "
                       "VALUES (?,?,?,?,0,?)", (web, "road", name, name,
                       json.dumps({"host_paid": False, "owner_user_id": uid, "owner_email": email}))).lastrowid
    return mid


def redeem(uid, mid, code):
    tok = "tok-%d-%d" % (uid, mid)
    conn.execute("INSERT OR REPLACE INTO sessions (token, user_id, kind, meet_id, created_at, expires) VALUES (?,?,?,?,?,?)",
                 (tok, uid, "event_owner", mid, auth._iso(auth._now()),
                  auth._iso(auth._now() + auth.timedelta(days=1))))
    conn.commit()
    c = application.test_client()
    c.set_cookie(auth.SESSION_COOKIE, tok)
    c.set_cookie("csrftoken", "x")
    return c.post(f"/meets/{mid}/host-redeem", json={"code": code}, headers={"X-CSRF-Token": "x"})


def used(code):
    return conn.execute("SELECT used_count FROM promo_codes WHERE code=?", (code,)).fetchone()[0]


def paid(mid):
    return json.loads(conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()[0])["host_paid"]


a = host("a@example.com"); a1 = event(a, "a@example.com", "A1"); a2 = event(a, "a@example.com", "A2")
b = host("b@example.com"); b1 = event(b, "b@example.com", "B1")
conn.commit()

r = redeem(a, a1, "ONCE")
assert r.status_code == 200 and r.get_json().get("paid") and paid(a1) and used("ONCE") == 1, ("case1", r.data)
print("PASS 1: first_event_only code publishes first event free")

r = redeem(a, a2, "ONCE")
assert r.status_code == 400 and "first event only" in r.get_json()["error"] and not paid(a2) and used("ONCE") == 1, ("case2", r.data)
print("PASS 2: same host's second event rejected, used_count unchanged")

r = redeem(b, b1, "ONCE")
assert r.status_code == 200 and paid(b1) and used("ONCE") == 2, ("case3", r.data)
print("PASS 3: different new host can still redeem")

r = redeem(a, a2, "ALWAYS")
assert r.status_code == 200 and paid(a2) and used("ALWAYS") == 1, ("case4", r.data)
print("PASS 4: normal code still works for repeat events")
print("ALL PASS")
