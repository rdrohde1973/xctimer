#!/usr/bin/env python3
"""WP-0011: /host landing copy + FIRSTRACE promo prefill. Run with a Python that has Flask installed:
    python3 scripts/test_host_landing.py
Temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, road          # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
auth.send_email = lambda *a, **k: None
db.init_db()
conn = db.connect()
conn.execute("INSERT OR IGNORE INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')")
conn.commit()
CSRF = {"X-CSRF-Token": "x"}
FAQ = ["What happens to my event after?", "Can runners pay online?", "Do I need an account?",
       "How do I get my link again?"]


def client():
    c = application.test_client()
    c.set_cookie("csrftoken", "x")
    return c


def banner_page(c, email, qs, name):
    assert c.get("/host" + qs).status_code == 200
    r = c.post("/host", data={"name": name, "date": "2099-01-01", "who": "W", "email": email,
                              **({"code": qs.split("code=")[1].split("&")[0]} if "code=" in qs and "<" not in qs else {})},
               headers=CSRF)
    assert r.status_code == 200
    tok = conn.execute("SELECT setup_token FROM users WHERE email=?", (email,)).fetchone()[0]
    r = c.get(f"/host/go/{tok}", follow_redirects=True)
    assert r.status_code == 200, r.status_code
    return r.get_data(as_text=True)


# (a) copy + fee from HOST_FEE_CENTS
r = client().get("/host"); h = r.get_data(as_text=True)
assert "FIRSTRACE" in h and "$100" in h and "$50" not in h
for q in FAQ:
    assert q in h, q
road.HOST_FEE_CENTS = 7500
h = client().get("/host").get_data(as_text=True)
assert "$75" in h and "$100 per" not in h
road.HOST_FEE_CENTS = 10000

# (b) code + utm carried through signup to the banner; attribution intact
page = banner_page(client(), "a@example.com", "?code=FIRSTRACE&utm_source=facebook", "Run A")
assert 'id="promocode"' in page and 'value="FIRSTRACE"' in page, "prefill missing"
row = conn.execute("SELECT * FROM host_attribution WHERE email='a@example.com'").fetchone()
assert row and row["utm_source"] == "facebook"

# (c) junk code ignored, never reflected
bad = "<script>alert(1)</script>"
h = client().get("/host?code=" + bad).get_data(as_text=True)
assert "alert(1)" not in h and 'name="code"' not in h
h = client().get("/host?code=lower").get_data(as_text=True)
assert 'name="code"' not in h
c = client()
c.post("/host", data={"name": "X", "date": "2099-01-01", "who": "W", "email": "c@example.com", "code": bad}, headers=CSRF)
tok = conn.execute("SELECT setup_token FROM users WHERE email='c@example.com'").fetchone()[0]
page = c.get(f"/host/go/{tok}", follow_redirects=True).get_data(as_text=True)
assert "alert(1)" not in page and 'id="promocode"' in page and 'value=""' in page

# (d) no code: visible, empty promo input
page = banner_page(client(), "d@example.com", "", "Run D")
m = re.search(r'<input id="promocode"[^>]*>', page)
assert m and 'value=""' in m.group(0) and "hidden" not in m.group(0) and "display:none" not in m.group(0)
print("OK")
