#!/usr/bin/env python3
"""Console tile: unique people who click through to the pricing page (1.114.0).
    python scripts/test_pricing_clicks.py
Uses a temp DB (XCTIMER_DB); never touches real data."""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, audit   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"
HOME = "http://localhost/welcome"


def browser(token):
    w = application.test_client()
    if token:
        w.set_cookie("csrftoken", token)
    return w


def click(w, ref=HOME, ua=UA):
    h = {"User-Agent": ua}
    if ref:
        h["Referer"] = ref
    assert w.get("/pricing", headers=h).status_code == 200


def rows():
    conn = db.connect()
    r = conn.execute("SELECT visitor, src FROM pricing_clicks ORDER BY id").fetchall()
    conn.close()
    return r


# 1. a click from one of our pages counts once per person, however many times they click
a, b = browser("alice-token"), browser("bob-token")
click(a); click(a); click(a, "http://localhost/start"); click(b, "http://localhost/")
assert audit.pricing_click_counts(1) == (2, 2), audit.pricing_click_counts(1)
assert len(rows()) == 4 and {r["src"] for r in rows()} == {"/welcome", "/start", "/"}
assert all(len(r["visitor"]) == 16 and "alice" not in r["visitor"] for r in rows())      # hashed, no raw token
print("PASS 1: clicks from our own pages are counted once per browser")

# 2. not a click: opened cold, came from another site, a reload, or a crawler
n = len(rows())
click(browser("carol"), ref=None)
click(browser("dave"), ref="https://www.facebook.com/")
click(browser("erin"), ref="http://localhost/pricing")
click(browser("bot"), ua="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
click(browser("fb"), ua="facebookexternalhit/1.1")
click(browser("none"), ua="")
assert len(rows()) == n and audit.pricing_click_counts(1) == (2, 2)
print("PASS 2: cold opens, other sites, reloads and crawlers are not counted")

# 3. the Super Admin's own clicks are left out; a signed-in coach's count
conn = db.connect()
did = conn.execute("INSERT INTO districts (name, slug) VALUES ('D','d')").lastrowid
sup = conn.execute("INSERT INTO users (email, name, role) VALUES ('root@x.example','Root','super_admin')").lastrowid
coach = conn.execute("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)",
                     (did, "coach@d.example", "Coach", "coach")).lastrowid
conn.commit(); conn.close()
root = browser("root-token"); root.set_cookie(auth.SESSION_COOKIE, auth.create_session(sup))
cw = browser("coach-token"); cw.set_cookie(auth.SESSION_COOKIE, auth.create_session(coach))
click(root, "http://localhost/admin/console"); click(cw, "http://localhost/insights")
assert audit.pricing_click_counts(1) == (3, 3) and rows()[-1]["src"] == "/insights"
print("PASS 3: the Super Admin is not counted; a coach who clicks See pricing is")

# 4. the time window: an old click counts all-time but not in the last hour or day
conn = db.connect()
conn.execute("INSERT INTO pricing_clicks (ts, visitor, src) VALUES ('2026-01-01T00:00:00+00:00','oldvisitor','/welcome')")
conn.commit(); conn.close()
assert audit.pricing_click_counts(1) == (3, 4) and audit.pricing_click_counts(168) == (3, 4)

# 5. the Console shows the tile
page = root.get("/admin/console?range=24h").get_data(as_text=True)
assert "PRICING BUTTON · UNIQUE PEOPLE" in page and "in the last 24 hours · 4 all time" in page
i = page.index("PRICING BUTTON")
assert ">3<div" in page[i:i + 300], page[i:i + 300]
assert cw.get("/admin/console").status_code == 403
print("PASS 4: the Console tile shows unique people for the chosen range and all time")
print("ALL PASS")
