#!/usr/bin/env python3
"""Search-engine basics for the public pages (1.115.0): sitemap, robots.txt, one canonical
address per page, a description of its own for each, and the price comparison on /pricing.
    python scripts/test_seo_pages.py"""
import json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ.pop("XC_PUBLIC_URL", None)
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod   # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
w = application.test_client()
BASE = "https://xctimer.com"


def page(path):
    r = w.get(path)
    assert r.status_code == 200, (path, r.status_code)
    return r.get_data(as_text=True)


def canon(html):
    m = re.findall(r'<link rel="canonical" href="([^"]+)">', html)
    assert len(m) == 1, m
    return m[0]


def desc(html):
    m = re.findall(r'<meta name="description" content="([^"]*)">', html)
    assert len(m) == 1, m
    return m[0]


# 1. sitemap lists the public pages (absolute addresses), and nothing private or with student names
r = w.get("/sitemap.xml")
assert r.status_code == 200 and r.mimetype == "application/xml"
locs = re.findall(r"<loc>([^<]+)</loc>", r.get_data(as_text=True))
GUIDES = ["/guides", "/guides/how-to-time-a-cross-country-meet",
          "/guides/how-to-run-a-track-meet", "/guides/how-to-organize-a-5k"]
assert locs == [BASE + p for p in ["/", "/pricing", "/start", "/host", "/security"] + GUIDES], locs
for loc in locs:
    page(loc[len(BASE):])                                  # every listed page really loads
assert not any(x in " ".join(locs) for x in ("/r/", "/results", "/meets", "/login"))
print("PASS 1: sitemap.xml lists the public pages and guides, and nothing else")

# 2. robots.txt points at the sitemap and keeps crawlers out of the app's private corners
r = w.get("/robots.txt")
txt = r.get_data(as_text=True)
assert r.status_code == 200 and r.mimetype == "text/plain"
assert f"Sitemap: {BASE}/sitemap.xml" in txt and "User-agent: *" in txt and "Allow: /" in txt
assert "Disallow: /admin/" in txt and "Disallow: /t/" in txt and "Disallow: /\n" not in txt
print("PASS 2: robots.txt allows the site, names the sitemap, and fences off private paths")

# 3. one address per page: "/" and "/welcome" are the same page and say so
assert canon(page("/")) == canon(page("/welcome")) == BASE + "/"
assert canon(page("/pricing?utm_source=fb")) == BASE + "/pricing"
assert canon(page("/start")) == BASE + "/start" and canon(page("/host")) == BASE + "/host"
assert canon(page("/security")) == BASE + "/security"
print("PASS 3: every public page names its one canonical address")

# 4. each page has its own description
d = {p: desc(page(p)) for p in ("/", "/pricing", "/start", "/host")}
assert len(set(d.values())) == 4, d
assert "$100 per meet" in d["/pricing"] and "school" in d["/start"].lower() and "fun run" in d["/host"].lower()
assert all(40 < len(v) <= 320 for v in d.values()), {k: len(v) for k, v in d.items()}
print("PASS 4: home, pricing, school sign-up and fun-run pages each have their own description")

# 5. the pricing page says what the alternatives cost
p = page("/pricing")
assert "What the alternatives cost" in p and "$500 to $1,000+" in p and "$265 to $685" in p
assert p.index("Hiring a timing company") < p.index("Desktop meet software") < p.index('<div class="crow you">')
assert p.count('<div class="amt">$100<span>') == 3 and "checked November 2026" in p
assert "What the alternatives cost" not in page("/welcome")           # prices stay off the marketing page
print("PASS 5: the pricing page compares $100 with a timing company and desktop meet software")

# 6. the words people search for are in the home page's title, description and first screen
home = page("/welcome")
title = re.search(r"<title>(.*?)</title>", home).group(1)
assert "Cross Country" in title and "Track Meet Timing" in title and title.endswith("| XCTimer") and len(title) < 80
assert "Cross country and track meet timing, scoring" in desc(home) and len(desc(home)) < 200
assert "<h1>Run the whole meet yourself.</h1>" in home and "The do-it-yourself meet manager:" in home   # pitch kept
assert "cross country scoring" in home and "meet manager for the whole meet" in home
assert "XCTimer Pricing: $100 per Meet" in page("/pricing") and "5K and fun run timing" in page("/host")
assert "<title>Cross country and track meet timing for your school" in page("/start")
print("PASS 6: titles and descriptions use the terms people search, with the pitch unchanged")

# 7. the how-to guides: one each, own title/description/canonical, linked from the public pages
seen = set()
for path in GUIDES:
    g = page(path)
    assert canon(g) == BASE + path and desc(g) not in seen and g.count("<h1>") == 1, path
    seen.add(desc(g))
    assert 'href="/pricing"' in g and 'href="/guides"' in g
# 1.127.0: the general scoring explainer is gone; its address sends people to XCTimer's own rules
r = w.get("/guides/how-to-score-a-cross-country-meet")
assert r.status_code == 301 and r.headers["Location"].endswith("/guides/how-to-time-a-cross-country-meet#results")
timing = page("/guides/how-to-time-a-cross-country-meet")
assert "poster board" in timing and "only once" in timing and "top to bottom" in timing
# 1.123.0: the XC timing guide walks XCTimer's own screens, not generic hand-timing advice.
for want in ("Phone Timer App", "listen for the gun", "FINISHER", "Lock bibs &amp; enable printing",
             "📷", "Walk-ups", "Lock results", "Time Trial", 'id="results"',
             "eighth runner and beyond holds no team place", "sixth runner finished first",
             "<title>How to Time a Cross Country Meet with XCTimer</title>"):
    assert want in timing, want
assert "how-to-score-a-cross-country-meet" not in timing
for gone in ("Start the clock with the gun", "One person starts the timer"):
    assert gone not in timing, gone
fivek = page("/guides/how-to-organize-a-5k")
assert "half price with code XCTIMERHALF" in fivek and "FIRSTRACE" not in fivek and 'href="/host"' in fivek
# 1.124.0: the 5K guide walks XCTimer's own screens, and is honest that sign-up has no waiver.
for want in ("Registration open", "Venmo", "Phone Timer App", "listen for the gun", "FINISHER", "📷",
             "Scan all races, one camera", "does not collect one", "30 days after the event date",
             "The course fly-over", "💧 Add water station", "🗺 Fly the course"):
    assert want in fivek, want
for guide in (timing, fivek):                     # 1.124.1: how many phones, scanning on its own phone
    assert "Three phones" in guide and "Two phones" in guide and "keep the scanning phone separate" in guide
assert "Charity run or school fundraiser?" in fivek and "Close registration before you print" not in fivek
for gone in ("$500 to $1,000 or more", "Include a waiver", "Three months out"):
    assert gone not in fivek, gone
assert "lap counters, not a race timer" in fivek                       # no false promise about jog-a-thons
track_g = " ".join(page("/guides/how-to-run-a-track-meet").split())
assert "<title>How to Run a School Track Meet with XCTimer</title>" in track_g
# 1.128.0: XCTimer serves high schools too, so public pages no longer say "middle school" / "junior high"
import re as _re
for _p in ["/", "/welcome", "/pricing", "/start", "/host", "/security", "/guides"] + [g for g in GUIDES if g != "/guides"]:
    _t = page(_p)
    assert not _re.search(r"(?i)junior[- ]high|middle[- ]school(?! / junior high)", _t.replace("Middle school / junior high", "")), _p
assert "8 plus 6 is 14, so each gets 7" in track_g and 'href="/start"' in track_g
assert "listen for the gun" in track_g and "pick their lane" in track_g and "TAP finisher" in track_g
assert "Pit tab" in track_g and "10 6" in track_g and "does not use misses to break the tie" in track_g
for generic in ("Start on the smoke", "rounded up", "torso", "round down"):      # no officiating-manual advice
    assert generic not in track_g, generic
assert "/guides/how-to-run-a-track-meet" in page("/guides") and "/guides/how-to-run-a-track-meet" in w.get("/sitemap.xml").get_data(as_text=True)
# the points tables in the guide are the ones the app ships with
from xctimerpkg import db as _db                                        # noqa: E402
for _name, _pts in _db.SEED_POINTS_TABLES:
    assert ", ".join(str(x) for x in json.loads(_pts)) in track_g, _name
assert w.get("/guides/no-such-guide").status_code == 404
assert 'href="/guides"' in home and 'href="/guides"' in page("/pricing") and "/guides/how-to-organize-a-5k" in page("/host")
# the worked example really is what the app computes
from xctimerpkg import xc                                              # noqa: E402
order = ["C", "M", "S", "C", "M", "M", "S", "C", "C", "M", "S", "C", "M", "S", "C", "M"]
teams = xc.team_scores([{"school": s, "place": i + 1, "elapsed_seconds": 600 + i, "bib": i + 1, "name": f"r{i}"}
                        for i, s in enumerate(order)])
got = {t["school"]: t["score"] for t in teams}
assert got == {"C": 26, "M": 29}, got
# ...and big squads: only a team's first seven hold a team place (the usual rule, 1.117.0)
big = ["A"] * 7 + ["B"] + ["A", "A"] + ["B"] * 4
got = {t["school"]: t["score"] for t in xc.team_scores(
    [{"school": s, "place": i + 1, "elapsed_seconds": 600 + i, "bib": i + 1, "name": f"r{i}"} for i, s in enumerate(big)])}
assert got == {"A": 15, "B": 50}, got          # 50, not 58: A's 8th and 9th runners hold no team place
assert "eighth runner and beyond holds no team place" in " ".join(timing.split())   # the guide says what the engine does
# the District Championship fill value still counts every team finisher (finishers + 1)
t = {x["school"]: x for x in xc.team_scores(
    [{"school": s} for s in ["A"] * 9 + ["B"] * 3], fill_missing=True)}
assert t["B"]["fill"] == 13 and t["B"]["places"] == [8, 9, 10, 13, 13], t["B"]
print("PASS 7: three XCTimer guides plus an index, and the guide states the scoring XCTimer computes")

# 8. www goes to the bare address; sign-in pages are kept out of search results
r = w.get("/login?next=/meets", base_url="http://www.xctimer.com")
assert r.status_code == 301 and r.headers["Location"] == "https://xctimer.com/login?next=/meets", r.headers.get("Location")
assert w.get("/pricing", base_url="https://xctimer.com").status_code == 200
assert w.post("/login", data={}, base_url="http://www.xctimer.com").status_code != 301       # only page loads move
login = page("/login")
assert '<meta name="robots" content="noindex">' in login
assert "noindex" not in home and "noindex" not in page("/pricing") and "noindex" not in timing
print("PASS 8: www redirects to the bare address and the sign-in page is marked noindex")
print("ALL PASS")
