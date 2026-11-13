#!/usr/bin/env python3
"""Search-engine basics for the public pages (1.115.0): sitemap, robots.txt, one canonical
address per page, a description of its own for each, and the price comparison on /pricing.
    python scripts/test_seo_pages.py"""
import os, re, sys, tempfile

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
assert locs == [BASE + p for p in ("/", "/pricing", "/start", "/host", "/security")], locs
for loc in locs:
    page(loc[len(BASE):])                                  # every listed page really loads
assert not any(x in " ".join(locs) for x in ("/r/", "/results", "/meets", "/login"))
print("PASS 1: sitemap.xml lists the five public pages and nothing else")

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
print("ALL PASS")
