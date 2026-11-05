#!/usr/bin/env python3
"""WP-0012: host-flow friction fixes F2, F3, F4, F6, F7. Needs Flask:
    python3 scripts/test_host_friction.py
Temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth              # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
sent = []
auth.send_email = lambda *a, **k: sent.append(a)
db.init_db()
conn = db.connect()
conn.execute("INSERT OR IGNORE INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')")
conn.commit()
CSRF = {"X-CSRF-Token": "x"}


def client():
    c = application.test_client()
    c.set_cookie("csrftoken", "x")
    return c


def post(c, email, name="Run F", **kw):
    return c.post("/host", data={"name": name, "date": "2099-01-01", "who": "W", "email": email, **kw},
                  headers=CSRF)


# F6: helper text under the date on /host
h = client().get("/host").get_data(as_text=True)
assert "Your event is removed 30 days after this date — download results first." in h, "F6"

# F2 + F3: confirmation page
c = client()
r = post(c, "f@example.com")
h = r.get_data(as_text=True)
assert r.status_code == 200
assert "XCTimer" in h and "spam" in h.lower(), "F2 sender/spam"
assert "Wrong address?" in h and 'href="/host"' in h, "F2 go back"
assert 'action="/host/resend"' in h and 'value="f@example.com"' in h and "Email my link again" in h, "F3"
n = len(sent)
r = c.post("/host/resend", data={"email": "f@example.com"}, headers=CSRF)
assert r.status_code == 200 and len(sent) == n + 1, "F3 resend works"

# F4: email owned by a non-web (coach/admin) account
conn.execute("INSERT INTO organizers (name, slug) VALUES ('Other','other')")
oid = conn.execute("SELECT id FROM organizers WHERE slug='other'").fetchone()[0]
conn.execute("INSERT INTO users (organizer_id, email, name, role) VALUES (?,?,?,?)",
             (oid, "coach@example.com", "Coach", "coach"))
conn.commit()
r = post(client(), "coach@example.com")
h = r.get_data(as_text=True)
assert r.status_code == 400 and "already registered" in h
assert "admin@xctimer.com" not in h, "F4 invented address"
assert "different email" in h and "mailto:rob@xctimer.com" in h and "get in touch" in h, "F4 alternative"

# F7: FIRSTRACE (100%) publish shows the next-step link; unpublished does not
conn.execute("INSERT INTO promo_codes (code, percent_off, active) VALUES ('FIRSTRACE', 100, 1)")
conn.commit()
c = client()
post(c, "g@example.com", name="Run G")
tok = conn.execute("SELECT setup_token FROM users WHERE email='g@example.com'").fetchone()[0]
page = c.get(f"/host/go/{tok}", follow_redirects=True)
url = page.request.path
mid = int(url.rstrip("/").split("/")[-1])
assert "Next: open registration" not in page.get_data(as_text=True)
r = c.post(f"/meets/{mid}/host-redeem", json={"code": "FIRSTRACE"}, headers=CSRF)
assert r.status_code == 200 and r.get_json().get("paid"), r.get_data(as_text=True)
page = c.get(f"/meets/{mid}?paid=1").get_data(as_text=True)
assert "Next: open registration" in page and 'href="#reg-settings"' in page, "F7 link"
assert 'id="reg-settings"' in page, "F7 anchor target exists"
print("OK")
