#!/usr/bin/env python3
"""WP-0009: UTM capture on /host + admin funnel report. Run with a Python that has Flask installed:
    python3 scripts/test_host_attribution.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import os, sys, tempfile, json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, road          # noqa: E402
from xctimerpkg.road import reap_web_events                   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
auth.send_email = lambda *a, **k: None                          # never send mail

db.init_db(); db.init_db()                                      # migration is idempotent
conn = db.connect()
conn.execute("INSERT OR IGNORE INTO organizers (name, slug) VALUES ('XCTimer Web','xctimer-web')")
conn.commit()
CSRF = {"X-CSRF-Token": "x"}


def client(session=None):
    c = application.test_client()
    c.set_cookie("csrftoken", "x")
    if session:
        c.set_cookie(auth.SESSION_COOKIE, session)
    return c


def login(role, email):
    web = conn.execute("SELECT id FROM organizers WHERE slug='xctimer-web'").fetchone()[0]
    uid = conn.execute("INSERT INTO users (organizer_id,email,name,role) VALUES (?,?,?,?)",
                       (web if role != "super_admin" else None, email, email, role)).lastrowid
    tok = "tok-" + email
    conn.execute("INSERT INTO sessions (token, user_id, kind, created_at, expires) VALUES (?,?,?,?,?)",
                 (tok, uid, "login", auth._iso(auth._now()), auth._iso(auth._now() + auth.timedelta(days=1))))
    conn.commit()
    return tok


def signup(email, qs="", name="Run"):
    c = client()
    r = c.get("/host" + qs)
    assert r.status_code == 200
    r = c.post("/host", data={"name": name, "date": "2099-01-01", "who": "W", "email": email}, headers=CSRF)
    assert r.status_code == 200, r.status_code
    return c


def attr(email):
    return conn.execute("SELECT * FROM host_attribution WHERE email=?", (email,)).fetchone()


# (a) UTM -> row; first touch wins
signup("A@Example.com", "?utm_source=facebook&utm_medium=organic&utm_campaign=firstrace&utm_content=post1&fbclid=abc")
r = attr("a@example.com")
assert r and (r["utm_source"], r["utm_medium"], r["utm_campaign"], r["utm_content"], r["fbclid"]) == \
    ("facebook", "organic", "firstrace", "post1", 1), dict(r) if r else r
assert r["meet_token"] and r["signed_up_at"]
c = client(); c.get("/host?utm_source=first"); c.get("/host?utm_source=second")
c.post("/host", data={"name": "n", "date": "2099-01-01", "who": "w", "email": "ft@example.com"}, headers=CSRF)
assert attr("ft@example.com")["utm_source"] == "first"
r = client().get("/welcome?utm_source=x")                       # landing sets cookie too
assert "xc_attr" in (r.headers.get("Set-Cookie") or "")

# seed second host: organic, published via promo
signup("b@example.com", "?utm_source=facebook&utm_campaign=other")
b_tok = attr("b@example.com")["meet_token"]
conn = db.connect()
conn.execute("UPDATE host_attribution SET published_at='2099-01-01T00:00:00' WHERE email='b@example.com'")
conn.execute("INSERT INTO promo_redemptions (email, code, meet_token, created_at) VALUES ('b@example.com','FIRSTRACE',?,'x')", (b_tok,))
conn.commit()

# (b) hostile value truncated + escaped
evil = "<script>alert(1)</script>" + "x" * 200
signup("evil@example.com", "?utm_source=%s&utm_campaign=evilc" % evil.replace("<", "%3C").replace(">", "%3E"))
assert len(attr("evil@example.com")["utm_source"]) == 100
sa = login("super_admin", "boss@example.com")
html = client(sa).get("/organizers/attribution").get_data(as_text=True)
assert "<script>alert(1)" not in html and "&lt;script&gt;" in html

# (c) counts: facebook/firstrace (host a + ft? ft has source 'first') and facebook/other (host b)
rows = {(r[0], r[1]): r[2:] for r in road._attribution_rows()}
assert rows[("facebook", "firstrace")] == (1, 1, 0, 0), rows
assert rows[("facebook", "other")] == (1, 1, 1, 1), rows
csvtxt = client(sa).get("/organizers/attribution.csv")
assert csvtxt.status_code == 200 and csvtxt.mimetype == "text/csv"
assert "facebook,other,1,1,1,1" in csvtxt.get_data(as_text=True)
assert "/organizers/attribution" in client(sa).get("/organizers").get_data(as_text=True)
# old rows fall outside the 90-day window
conn.execute("UPDATE host_attribution SET signed_up_at='2000-01-01T00:00:00' WHERE email='b@example.com'")
conn.commit()
assert ("facebook", "other") not in {(r[0], r[1]) for r in road._attribution_rows()}

# (d) non-super-admins get 403 (and anonymous is not served)
rd = login("race_director", "rd@example.com")
for url in ("/organizers/attribution", "/organizers/attribution.csv"):
    assert client(rd).get(url).status_code == 403, url
    assert client().get(url).status_code in (302, 401, 403), url

# (e) reaper leaves host_attribution intact
before = conn.execute("SELECT COUNT(*) FROM host_attribution").fetchone()[0]
conn.execute("UPDATE meets SET date='2000-01-01'")
conn.commit()
assert reap_web_events(conn, "2099-06-01") > 0
assert conn.execute("SELECT COUNT(*) FROM host_attribution").fetchone()[0] == before > 0
print("OK")
