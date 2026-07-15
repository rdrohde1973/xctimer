"""XCTimer platform — Flask app factory & boot (handoff §5).

Phase 1: password auth + email setup/reset links, multi-device sessions, the 4
roles, district scoping + Super-Admin switcher, user/district/school management,
and the meet-day no-login QR session. XC/Track engines land in Phases 3-4.

Serve: waitress on XC_HOST:XC_PORT (defaults 127.0.0.1:5006), via the systemd unit.
"""
import hmac
import os
import secrets

from flask import Flask, jsonify, g, redirect, request

from . import db, auth, audit
from .auth import bp as auth_bp
from .tenancy import bp as tenancy_bp
from .schools import bp as schools_bp
from .meets import bp as meets_bp
from .xc import bp as xc_bp
from .track import bp as track_bp
from .admin import bp as admin_bp
from .insights import bp as insights_bp
from .phone import bp as phone_bp
from .waivers import bp as waivers_bp

APP_VERSION = "0.62.4-audit-killswitch"

LANDING = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer — meet timing &amp; coach management for junior high &amp; middle school XC &amp; track</title>
<meta name="description" content="Affordable, simple cross-country and track & field meet timing and roster management built for junior high & middle school — live results the whole crowd can follow, AI roster import, and athlete insights. Built by a coach of 7 years and a parent of three XC & track kids.">
<style>
  :root{--navy:#164271;--navy-d:#0f3157;--orange:#ea6a2d;--orange-d:#cf5a22;
        --gray:#868686;--ink:#20303f;--bg:#f5f8fc;--card:#ffffff;--line:#e3e9f1}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;font:16px/1.65 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       color:var(--ink);background:var(--bg)}
  a{color:var(--navy);text-decoration:none}
  .wrap{max-width:1080px;margin:0 auto;padding:0 1.2rem}
  .btn{display:inline-block;background:var(--orange);color:#fff;font-weight:700;
       padding:.75rem 1.7rem;border-radius:11px;font-size:1.02rem;
       box-shadow:0 6px 18px rgba(234,106,45,.32)}
  .btn:hover{background:var(--orange-d)}
  .btn.ghost{background:transparent;color:var(--navy);box-shadow:none;border:1.5px solid #cdd8e6}
  .btn.ghost:hover{background:#eef3f9}
  /* nav */
  nav{position:sticky;top:0;z-index:10;background:rgba(245,248,252,.9);
      backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
  nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px}
  nav img{height:34px;width:auto}
  nav a.signin{font-weight:700;color:var(--navy);padding:.5rem 1.1rem;border-radius:9px}
  nav a.signin:hover{background:#eef3f9}
  /* hero */
  header.hero{background:radial-gradient(120% 90% at 50% -10%,#ffffff 0%,#eaf0f7 70%,#e2e9f2 100%);
              padding:3.6rem 0 3.2rem;text-align:center;border-bottom:1px solid var(--line)}
  .hero img.logo{width:min(430px,84vw);height:auto;filter:drop-shadow(0 10px 30px rgba(22,66,113,.14))}
  .hero h1{font-size:clamp(1.7rem,4.6vw,2.7rem);line-height:1.15;margin:1.4rem auto .3rem;
           max-width:15ch;color:var(--navy);letter-spacing:-.01em}
  .hero p.sub{font-size:clamp(1rem,2.4vw,1.2rem);color:#43586c;max-width:44ch;margin:.6rem auto 1.8rem}
  .hero .cta{display:flex;gap:.8rem;justify-content:center;flex-wrap:wrap}
  .pill{display:inline-block;background:#fff;border:1px solid var(--line);color:var(--gray);
        border-radius:999px;padding:.3rem .9rem;font-size:.82rem;font-weight:600;margin-bottom:1.1rem}
  .pill b{color:var(--orange)}
  /* sections */
  section{padding:3.4rem 0}
  h2{font-size:clamp(1.4rem,3.4vw,2rem);color:var(--navy);letter-spacing:-.01em;margin:.2em 0 .5em}
  .lead{font-size:1.12rem;color:#43586c;max-width:60ch}
  .split{display:grid;grid-template-columns:1fr 1fr;gap:2.4rem;align-items:center}
  .contrast{background:#fff;border:1px solid var(--line);border-radius:16px;padding:1.6rem 1.8rem}
  .contrast h3{margin:.2em 0 .5em;color:var(--navy)}
  .contrast .row{display:flex;gap:.7rem;padding:.45rem 0;align-items:flex-start}
  .x{color:#c0483f;font-weight:800}.ok{color:#2e8b57;font-weight:800}
  /* features */
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1.1rem;margin-top:1.6rem}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.3rem 1.4rem}
  .card .ic{font-size:1.6rem}
  .card h3{margin:.5rem 0 .3rem;font-size:1.08rem;color:var(--navy)}
  .card p{margin:0;color:#4a5f73;font-size:.95rem}
  /* coach story band */
  .band{background:linear-gradient(135deg,var(--navy) 0%,var(--navy-d) 100%);color:#eaf1f8}
  .band h2{color:#fff}
  .band .lead{color:#c3d3e4}
  .quote{border-left:4px solid var(--orange);padding:.4rem 0 .4rem 1.2rem;margin:1.4rem 0;
          font-size:1.25rem;font-weight:600;color:#fff;max-width:40ch}
  .stat{display:flex;gap:2.2rem;flex-wrap:wrap;margin-top:1.4rem}
  .stat div b{display:block;font-size:2rem;color:var(--orange);line-height:1}
  .stat div span{color:#c3d3e4;font-size:.9rem}
  /* final cta */
  .final{text-align:center}
  .final h2{margin-bottom:.4rem}
  footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--gray);font-size:.85rem;text-align:center}
  @media(max-width:720px){ .split{grid-template-columns:1fr;gap:1.4rem} section{padding:2.6rem 0} }
</style></head><body>

<nav><div class="wrap">
  <img src="/static/branding/xctimer.png" alt="XCTimer">
  <a class="signin" href="/login">Sign in</a>
</div></nav>

<header class="hero"><div class="wrap">
  <img class="logo" src="/static/branding/xctimer.png" alt="XCTimer">
  <div class="pill">Built for <b>junior high &amp; middle school</b> cross country &amp; track</div>
  <h1>Meet timing &amp; coach management, made for junior high &amp; middle school.</h1>
  <p class="sub">Rosters, live timing, field events, and instant results — everything a
     junior high or middle school XC or track meet needs, and nothing it doesn't.</p>
  <div class="cta">
    <a class="btn" href="/login">Sign in</a>
    <a class="btn ghost" href="#features">See what it does</a>
  </div>
</div></header>

<section><div class="wrap split">
  <div>
    <h2>Made for jr high &amp; middle school — not a hand-me-down from high school.</h2>
    <p class="lead">The big timing systems are built for high school and college programs, and
    they're priced and complicated to match. Coaches end up paying for enterprise features
    they'll never use and fighting menus on meet day. XCTimer does what a junior high meet
    actually needs — simple enough to run from your phone, priced for a jr-high budget.</p>
  </div>
  <div class="contrast">
    <h3>The difference</h3>
    <div class="row"><span class="x">✕</span><div>Enterprise software priced for varsity budgets</div></div>
    <div class="row"><span class="ok">✓</span><div>Affordable and built for junior high</div></div>
    <div class="row"><span class="x">✕</span><div>Menus and settings you'll never use</div></div>
    <div class="row"><span class="ok">✓</span><div>Run a whole meet from your phone</div></div>
    <div class="row"><span class="x">✕</span><div>Made for high school &amp; college rules</div></div>
    <div class="row"><span class="ok">✓</span><div>Works the way a jr-high meet really runs</div></div>
  </div>
</div></section>

<section id="features"><div class="wrap">
  <h2>Everything meet day needs</h2>
  <p class="lead">From the roster to the results table — one tool for cross country and track &amp; field.</p>
  <div class="grid">
    <div class="card"><div class="ic">📋</div><h3>AI roster intake &amp; bib stickers</h3>
      <p>Drop in a spreadsheet, PDF, or even a photo of a roster — AI reads and cleans up the names — then auto-assign bibs and print Avery stickers with a scannable code.</p></div>
    <div class="card"><div class="ic">⏱️</div><h3>Live timing from your phone</h3>
      <p>Tap finishers for cross country, time heats and lanes for track — right from a phone at the line.</p></div>
    <div class="card"><div class="ic">📏</div><h3>Field events in feet &amp; inches</h3>
      <p>Long Jump and Shot Put with all three attempts, plus a High Jump make/miss grid — the way officials record them.</p></div>
    <div class="card"><div class="ic">🖨️</div><h3>Heat sheets &amp; scan</h3>
      <p>Print clean heat sheets, mark them up at the event, then snap a photo — the marks read straight in.</p></div>
    <div class="card"><div class="ic">🏆</div><h3>Instant results</h3>
      <p>A public results page with a QR to share, team scoring by grade &amp; gender, and an Excel export.</p></div>
    <div class="card"><div class="ic">📱</div><h3>Meet-day made easy</h3>
      <p>A phone app for coaches and a no-login QR for helpers — everyone can pitch in without an account.</p></div>
    <div class="card"><div class="ic">🤖</div><h3>AI athlete insights</h3>
      <p>Just ask — an athlete's PRs and season progress, or a district record — and get an answer pulled straight from your own results.</p></div>
  </div>
</div></section>

<style>
#live{background:linear-gradient(180deg,#ffffff 0%,#eaf1f9 100%);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
#live .pill{background:#fff}
#live .livelist{list-style:none;padding:0;margin:1.3rem 0 0;display:grid;gap:.65rem}
#live .livelist li{display:flex;gap:.6rem;align-items:flex-start;color:#3a4f63;font-size:1.02rem}
#live .livelist .ck{color:#2e8b57;font-weight:800;flex-shrink:0}
#live .livenote{margin:1.3rem 0 0;font-style:italic;color:#4a5f73;font-size:1.02rem;
                border-left:3px solid var(--orange);padding-left:.9rem}
.livedemo{background:#fff;border:2px solid var(--orange);border-radius:18px;padding:1.2rem 1.3rem;
          box-shadow:0 16px 38px rgba(22,66,113,.18);max-width:340px;margin:0 auto}
.livedemo .hd{display:flex;align-items:center;gap:.5rem;font-weight:800;color:var(--orange);font-size:.92rem}
.livedemo .dot{width:.7rem;height:.7rem;border-radius:50%;background:#2e9e5b;animation:livepulse 1.1s infinite}
@keyframes livepulse{50%{opacity:.22}}
.livedemo .clk{font-size:2.8rem;font-weight:800;text-align:center;color:var(--navy);
               font-variant-numeric:tabular-nums;margin:.25rem 0 .55rem;letter-spacing:.5px}
.livedemo table{width:100%;border-collapse:collapse;font-size:.95rem}
.livedemo td{padding:.42rem .2rem;border-top:1px solid var(--line)}
.livedemo .pl{color:var(--orange);font-weight:800;width:1.7rem}
.livedemo .tm{text-align:right;font-variant-numeric:tabular-nums;color:#3a4f63}
.livedemo .mut{color:var(--gray)}
</style>
<section id="live"><div class="wrap split">
  <div>
    <div class="pill">🟢 Live results — everyone's favorite feature</div>
    <h2>The whole crowd follows every race — live.</h2>
    <p class="lead">Share one link or QR code and families watch results roll in
    <b>the instant each runner crosses the line</b> — from the fence, the bleachers, or grandparents
    watching from three states away. A live race clock, finishers appearing in order, updated in
    real time. No app to install, no account to create — just tap the link. It turns a quiet finish
    chute into a scoreboard the whole meet is glued to.</p>
    <ul class="livelist">
      <li><span class="ck">✓</span> Live race clock, in sync on every phone in the stands</li>
      <li><span class="ck">✓</span> Finishers pop in the moment they're timed</li>
      <li><span class="ck">✓</span> One QR code — hundreds can watch at once</li>
      <li><span class="ck">✓</span> No app, no login, works on any phone</li>
    </ul>
    <p class="livenote">"I spent years in those stands as a parent of three runners — this is the
    feature I always wished I had."</p>
  </div>
  <div>
    <div class="livedemo">
      <div class="hd"><span class="dot"></span> LIVE · Girls 7th Grade 1600m</div>
      <div class="clk">5:38.2</div>
      <table>
        <tr><td class="pl">1</td><td>Ava Ramirez <span class="mut">· Maple</span></td><td class="tm">5:31.4</td></tr>
        <tr><td class="pl">2</td><td>Sofia Chen <span class="mut">· Ridgeline</span></td><td class="tm">5:33.9</td></tr>
        <tr><td class="pl">3</td><td>Harper Diaz <span class="mut">· Maple</span></td><td class="tm">5:36.1</td></tr>
        <tr><td class="pl">4</td><td class="mut">… crossing</td><td class="tm"></td></tr>
      </table>
    </div>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <h2>Built by a coach — and a cross-country &amp; track parent.</h2>
  <p class="lead">XCTimer was built by a former junior high coach who personally timed meets for
  seven years — <b style="color:#fff">and a parent of three cross-country and track kids</b> who
  spent just as many seasons in the stands. That's both sides of every meet: running it from the
  finish line, and standing in the bleachers wanting to know, right now, how your own kid just did.
  Every feature comes from that real experience — the bib stickers, the tap timer, the make/miss
  high jump grid, scanning a marked-up sheet, and the live results the whole crowd can follow.</p>
  <div class="quote">"As a coach, I wanted a tool any coach could run. As a parent, I wanted to see my kid's race the moment it happened."</div>
  <div class="stat">
    <div><b>7 yrs</b><span>timing meets</span></div>
    <div><b>3 kids</b><span>XC &amp; track athletes</span></div>
    <div><b>Both sides</b><span>coach &amp; parent</span></div>
  </div>
</div></section>

<section class="final"><div class="wrap">
  <h2>Ready to run a simpler meet?</h2>
  <p class="lead" style="margin:.4rem auto 1.4rem">Sign in to get started, or reach out to bring XCTimer to your district.</p>
  <div class="cta" style="display:flex;gap:.8rem;justify-content:center;flex-wrap:wrap">
    <a class="btn" href="/login">Sign in</a>
    <a class="btn ghost" href="mailto:admin@xctimer.com?subject=XCTimer%20for%20our%20district">Get in touch</a>
  </div>
</div></section>

<footer>© XCTimer · xctimer.com · timing &amp; coach management for junior high cross country &amp; track
<br><a href="/security" style="color:var(--navy);font-weight:700">Security &amp; data privacy</a></footer>
</body></html>"""


SECURITY = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Security &amp; data privacy — XCTimer</title>
<meta name="description" content="How XCTimer protects student-athlete data: encryption in transit, sign-in-gated access, district isolation, hardened sessions, daily backups, and strict data minimization.">
<style>
  :root{--navy:#164271;--navy-d:#0f3157;--orange:#ea6a2d;--gray:#868686;--ink:#20303f;--bg:#f5f8fc;--line:#e3e9f1}
  *{box-sizing:border-box}
  body{margin:0;font:16px/1.7 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg)}
  a{color:var(--navy)}
  .wrap{max-width:820px;margin:0 auto;padding:0 1.2rem}
  nav{position:sticky;top:0;z-index:10;background:rgba(245,248,252,.92);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
  nav .wrap{display:flex;align-items:center;justify-content:space-between;height:64px;max-width:1080px}
  nav img{height:34px} nav a.signin{font-weight:700;color:var(--navy);padding:.5rem 1.1rem;border-radius:9px}
  header.hd{background:radial-gradient(120% 90% at 50% -10%,#fff 0%,#eaf0f7 75%,#e2e9f2 100%);padding:3rem 0 2.4rem;border-bottom:1px solid var(--line)}
  header.hd h1{color:var(--navy);font-size:clamp(1.8rem,4.5vw,2.5rem);margin:.2rem 0 .4rem;letter-spacing:-.01em}
  header.hd p{color:#43586c;font-size:1.1rem;margin:0;max-width:60ch}
  main{padding:2.4rem 0 1rem}
  section{border-top:1px solid var(--line);padding:2rem 0}
  section:first-child{border-top:none}
  .num{color:var(--orange);font-weight:800;font-size:.8rem;letter-spacing:.14em}
  h2{color:var(--navy);font-size:1.4rem;margin:.15rem 0 1rem;letter-spacing:-.01em}
  h3{color:var(--ink);font-size:1.02rem;margin:1.2rem 0 .1rem}
  h3 .em{color:var(--orange)}
  p.sub{color:#4a5f73;margin:.1rem 0 0}
  .no{list-style:none;padding:0;margin:.6rem 0 0;display:grid;gap:.45rem}
  .no li{display:flex;gap:.6rem;color:#3a4f63}
  .no .x{color:#c0483f;font-weight:800;flex-shrink:0}
  .updated{color:var(--gray);font-size:.85rem;margin-top:.5rem}
  footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--gray);font-size:.85rem;text-align:center}
  .btn{display:inline-block;background:var(--orange);color:#fff;font-weight:700;padding:.6rem 1.4rem;border-radius:10px;text-decoration:none;margin-top:.4rem}
</style></head><body>
<nav><div class="wrap">
  <a href="/"><img src="/static/branding/xctimer.png" alt="XCTimer"></a>
  <a class="signin" href="/login">Sign in</a>
</div></nav>
<header class="hd"><div class="wrap">
  <h1>Security &amp; data privacy</h1>
  <p>XCTimer holds information about student athletes, so we treat it carefully. Here's exactly
     how we protect your data, what we collect, and what we deliberately don't.</p>
</div></header>
<main class="wrap">

  <section>
    <div class="num">01</div><h2>How we protect your data</h2>
    <h3><span class="em">Encrypted in transit.</span></h3>
    <p class="sub">Every connection to XCTimer runs over HTTPS/TLS. Nothing you send or view crosses the internet in the clear.</p>
    <h3><span class="em">Locked behind sign-in.</span></h3>
    <p class="sub">Rosters, results, and contact details are only reachable by signed-in users. The one thing that can be public is a live results page — and only when a coach chooses to share its link.</p>
    <h3><span class="em">Your district, fenced off.</span></h3>
    <p class="sub">Each district's data is isolated. A coach or admin in one district cannot see another district's athletes, meets, or results.</p>
    <h3><span class="em">Least privilege by role.</span></h3>
    <p class="sub">Coaches, timers, district admins, and platform admins each see only what their job needs — nothing more.</p>
    <h3><span class="em">Hardened sessions.</span></h3>
    <p class="sub">Sign-in cookies are locked to your browser (HttpOnly, Secure, SameSite), sessions expire on their own after inactivity and on a hard cap, and every action that changes data carries an anti-forgery (CSRF) token.</p>
    <h3><span class="em">Defense in depth.</span></h3>
    <p class="sub">A strict Content-Security-Policy, modern security headers, parameterized database queries, and a no-cache rule on every page that shows student data.</p>
    <h3><span class="em">Locked down at rest.</span></h3>
    <p class="sub">The database lives on a private server with no public inbound access — reachable only through the authenticated app, behind a managed network edge.</p>
    <h3><span class="em">Daily backups.</span></h3>
    <p class="sub">Rosters and results are backed up automatically every night, so a bad day never means lost data.</p>
  </section>

  <section>
    <div class="num">02</div><h2>What we hold — and what we don't</h2>
    <h3><span class="em">What's in your account.</span></h3>
    <p class="sub">Athlete rosters (name, grade, school, bib), meet entries and results/times, and any optional contact, parent, emergency, physical, or waiver details a coach chooses to add. That's the whole list.</p>
    <h3><span class="em">What we deliberately don't collect.</span></h3>
    <ul class="no">
      <li><span class="x">✕</span> No Social Security numbers.</li>
      <li><span class="x">✕</span> No bank account or credit-card numbers.</li>
      <li><span class="x">✕</span> No third-party advertising or tracking scripts.</li>
      <li><span class="x">✕</span> We never sell or share your data — with anyone.</li>
    </ul>
    <h3><span class="em">Only what a meet needs.</span></h3>
    <p class="sub">Because these are junior-high athletes, we keep the footprint small on purpose. A field exists because a real meet or a real waiver uses it — and it's built with student-privacy expectations (FERPA / COPPA) in mind.</p>
    <h3><span class="em">Your data on the way out.</span></h3>
    <p class="sub">Export full results to Excel anytime. Want a student's — or your whole district's — data removed? Ask us and we'll delete it.</p>
  </section>

  <section>
    <div class="num">03</div><h2>If something goes wrong</h2>
    <h3><span class="em">We'll tell you.</span></h3>
    <p class="sub">If a security incident ever affected your data, we'll notify affected districts promptly — our target is within 72 hours of confirming it — with what we know and what we're doing about it.</p>
    <h3><span class="em">Where it runs.</span></h3>
    <p class="sub">XCTimer is hosted on dedicated servers in the United States (Hillsboro, Oregon).</p>
  </section>

  <section>
    <div class="num">04</div><h2>Talk to us</h2>
    <h3><span class="em">Security researchers.</span></h3>
    <p class="sub">Found something? Email <a href="mailto:admin@xctimer.com">admin@xctimer.com</a>. We welcome good-faith reports and won't pursue researchers acting in good faith.</p>
    <h3><span class="em">Schools, districts &amp; vendor reviews.</span></h3>
    <p class="sub">Need a security questionnaire filled out, or have a district data-privacy requirement? Email <a href="mailto:admin@xctimer.com">admin@xctimer.com</a> — happy to help.</p>
    <a class="btn" href="/">← Back to XCTimer</a>
  </section>

</main>
<footer>© XCTimer · xctimer.com · <a href="/" style="color:var(--navy)">Home</a></footer>
</body></html>"""


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("XCTIMER_SECRET", "dev-insecure-change-me")
    # Cookie hardening (security audit MEDIUM-2). SECURE only in prod (behind
    # HTTPS at Cloudflare) — XC_SECURE_COOKIES=1 there; unset on LAN http dev.
    _secure = bool(os.environ.get("XC_SECURE_COOKIES"))
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=_secure,
    )

    db.init_db()

    app.before_request(auth.load_principal)
    app.before_request(auth.demo_readonly_guard)

    for bp in (auth_bp, tenancy_bp, schools_bp, meets_bp, xc_bp, track_bp,
               admin_bp, insights_bp, phone_bp, waivers_bp):
        app.register_blueprint(bp)

    # --- CSRF protection (double-submit cookie), compliance Phase 2 ---
    # The token cookie is issued in the existing _security_headers after_request below;
    # the client (ui.CSRF_JS) echoes it as X-CSRF-Token / a hidden _csrf form field.
    CSRF_COOKIE = "csrftoken"
    _CSRF_SAFE = {"GET", "HEAD", "OPTIONS", "TRACE"}

    @app.before_request
    def _csrf_protect():
        if request.method in _CSRF_SAFE:
            return
        cookie = request.cookies.get(CSRF_COOKIE)
        # header first (covers fetch/JSON/file uploads without parsing the body)
        sent = request.headers.get("X-CSRF-Token") or request.form.get("_csrf")
        if not cookie or not sent or not hmac.compare_digest(str(cookie), str(sent)):
            from .ui import error_page
            return error_page(403, "Security check failed",
                              "Your page's security token was missing or expired. "
                              "Please reload the page and try again."), 403

    # Access log -> journald: one parseable line per request, for the Super-Admin console.
    import logging as _logging
    from flask import request as _request
    _acc = _logging.getLogger("xctimer.access")
    if not _acc.handlers:
        _h = _logging.StreamHandler()
        _h.setFormatter(_logging.Formatter("%(message)s"))
        _acc.addHandler(_h)
        _acc.setLevel(_logging.INFO)
        _acc.propagate = False

    @app.after_request
    def _access_log(resp):
        try:
            p = _request.path or "-"
            if not p.startswith("/admin/console"):   # console must not log itself
                ip = (_request.headers.get("CF-Connecting-IP")
                      or _request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                      or _request.remote_addr or "-")
                prin = getattr(g, "principal", None)
                who = (getattr(prin, "email", None)
                       or ("meet-timer" if getattr(prin, "meet_scope", None) else "-")) if prin else "-"
                _acc.info(f"XCLOG REQ {ip} {resp.status_code} {_request.method} {p} user={who}")
        except Exception:  # noqa: BLE001
            pass
        return resp

    @app.after_request
    def _audit(resp):
        audit.record_request(resp.status_code)
        return resp

    @app.get("/")
    def landing():
        if getattr(g, "principal", None):
            from .ui import home_url
            return redirect(home_url(g.principal))
        return LANDING

    @app.get("/security")
    def security():
        return SECURITY

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", version=APP_VERSION)

    @app.get("/manifest.webmanifest")
    def manifest():
        # PWA manifest so "Add to Home Screen" installs a clean standalone app.
        return jsonify({
            "name": "XCTimer", "short_name": "XCTimer",
            "start_url": "/phone", "scope": "/",
            "display": "standalone", "orientation": "portrait",
            "background_color": "#0a1728", "theme_color": "#0a1728",
            "icons": [
                {"src": "/static/branding/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/static/branding/icon-512.png", "sizes": "512x512", "type": "image/png",
                 "purpose": "any maskable"},
            ],
        })

    @app.get("/.well-known/security.txt")
    def security_txt():
        from datetime import datetime, timedelta, timezone
        from flask import Response
        exp = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
        base = os.environ.get("XC_PUBLIC_URL", "https://xctimer.com")
        body = (f"Contact: mailto:admin@xctimer.com\n"
                f"Expires: {exp}\n"
                f"Preferred-Languages: en\n"
                f"Canonical: {base}/.well-known/security.txt\n")
        return Response(body, mimetype="text/plain")

    @app.after_request
    def _security_headers(resp):
        # HTTP security headers (audit HIGH-1). Belt-and-suspenders with Cloudflare.
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        # Inline <style>/<script> are used throughout, so 'unsafe-inline' is required;
        # frame-ancestors 'none' is the key clickjacking win.
        resp.headers.setdefault("Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'")
        if _secure:
            resp.headers.setdefault("Strict-Transport-Security",
                                    "max-age=31536000; includeSubDomains")
        # Don't let authenticated pages sit in caches (audit LOW-1).
        if getattr(g, "principal", None):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Pragma"] = "no-cache"
        # Issue a readable CSRF token cookie once per browser (double-submit pattern).
        if not request.cookies.get(CSRF_COOKIE):
            resp.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32),
                            samesite="Lax", secure=_secure, max_age=60 * 60 * 24 * 30)
        return resp

    from .ui import error_page

    @app.errorhandler(403)
    def _e403(e):
        return error_page(403, "Not allowed", "You don't have access to that."), 403

    @app.errorhandler(404)
    def _e404(e):
        return error_page(404, "Not found", "That page or record doesn't exist."), 404

    @app.errorhandler(500)
    def _e500(e):
        return error_page(500, "Something went wrong", "An unexpected error occurred."), 500

    return app


app = create_app()


def main():
    from waitress import serve

    host = os.environ.get("XC_HOST", "127.0.0.1")
    port = int(os.environ.get("XC_PORT", "5006"))
    # Thread pool = max concurrent requests. Default 24 (waitress default is only 4):
    # gives headroom so a burst of write requests waiting on SQLite's single writer
    # can't starve everyone else (spectators, other timers, healthz). Override via env.
    threads = int(os.environ.get("XC_THREADS", "24"))
    print(f"XCTimer {APP_VERSION} serving on {host}:{port} ({threads} threads)")
    serve(app, host=host, port=port, threads=threads)


if __name__ == "__main__":
    main()
