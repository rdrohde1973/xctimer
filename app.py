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
from .road import bp as road_bp

APP_VERSION = "1.61.0-meetcam-onsight"

LANDING = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>XCTimer — the do-it-yourself meet manager for junior high &amp; middle school XC &amp; track</title>
<meta name="description" content="Run your own cross-country or track meet — no expensive timing company required. XCTimer is a complete do-it-yourself meet manager for junior high & middle school: rosters, live timing, field events, scoring, and live results the whole crowd can follow. Built by a coach of 8 years and a parent of three XC & track kids.">
<style>
  :root{--ink:#0c1929;--ink2:#13283f;--orange:#f0641e;--orange-d:#d4530f;--gray:#6b7684;
        --body:#212b36;--bg:#f6f7f9;--card:#ffffff;--line:#e6e9ee;--green:#2e9e5b}
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;font:16px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
       color:var(--body);background:#fff}
  a{color:var(--orange-d);text-decoration:none}
  .wrap{max-width:1060px;margin:0 auto;padding:0 1.2rem}
  .btn{display:inline-block;background:var(--orange);color:#fff;font-weight:700;
       padding:.75rem 1.7rem;border-radius:11px;font-size:1.02rem;
       box-shadow:0 6px 18px rgba(240,100,30,.30)}
  .btn:hover{background:var(--orange-d)}
  .btn.ghost{background:transparent;color:#fff;box-shadow:none;border:1.5px solid rgba(255,255,255,.35)}
  .btn.ghost:hover{background:rgba(255,255,255,.08)}
  .btn.ghost2{background:transparent;color:var(--ink);box-shadow:none;border:1.5px solid #cfd6de}
  .btn.ghost2:hover{background:#eef1f4}
  .kicker{display:inline-block;color:var(--orange);font-weight:800;font-size:.8rem;
          letter-spacing:.14em;text-transform:uppercase;margin-bottom:.8rem}
  /* nav */
  nav{position:sticky;top:0;z-index:10;background:rgba(12,25,41,.93);backdrop-filter:blur(8px);
      border-bottom:1px solid rgba(255,255,255,.08)}
  nav .wrap{display:flex;align-items:center;justify-content:space-between;height:60px}
  .wordmark{font-weight:800;font-size:1.25rem;letter-spacing:-.02em}
  .wordmark .bx,.wordmark .bi{color:var(--orange)}
  .wordmark .bt{color:#fff}
  .wordmark .bd{color:#7f93a8;font-size:.85em;font-weight:700}
  nav a.signin{font-weight:700;color:#fff;padding:.45rem 1.1rem;border-radius:9px;
               border:1.5px solid rgba(255,255,255,.25)}
  nav a.signin:hover{background:rgba(255,255,255,.1)}
  /* hero — dark, message left, live demo right */
  header.hero{background:linear-gradient(160deg,var(--ink2) 0%,var(--ink) 60%,#0a1420 100%);
              color:#e9eef5;padding:3.8rem 0 4.2rem;border-bottom:4px solid var(--orange)}
  .hero .wrap{display:grid;grid-template-columns:1.15fr .85fr;gap:3rem;align-items:center}
  .hero h1{font-size:clamp(2rem,5vw,3rem);line-height:1.1;margin:0 0 .7rem;color:#fff;
           letter-spacing:-.015em}
  .hero p.sub{font-size:clamp(1rem,2.2vw,1.15rem);color:#aebdcd;max-width:46ch;margin:0 0 1.7rem}
  .hero .cta{display:flex;gap:.8rem;flex-wrap:wrap}
  /* live results demo card (hero visual) */
  .livedemo{background:#fff;border-radius:18px;padding:1.2rem 1.3rem;color:var(--body);
            box-shadow:0 24px 60px rgba(0,0,0,.45),0 0 0 2px var(--orange);
            max-width:340px;margin:0 auto}
  .livedemo .hd{display:flex;align-items:center;gap:.5rem;font-weight:800;color:var(--orange);
                font-size:.92rem}
  .livedemo .dot{width:.7rem;height:.7rem;border-radius:50%;background:var(--green);
                 animation:livepulse 1.1s infinite}
  @keyframes livepulse{50%{opacity:.22}}
  .livedemo .clk{font-size:2.8rem;font-weight:800;text-align:center;color:var(--ink);
                 font-variant-numeric:tabular-nums;margin:.25rem 0 .55rem;letter-spacing:.5px}
  .livedemo table{width:100%;border-collapse:collapse;font-size:.95rem}
  .livedemo td{padding:.42rem .2rem;border-top:1px solid var(--line)}
  .livedemo .pl{color:var(--orange);font-weight:800;width:1.7rem}
  .livedemo .tm{text-align:right;font-variant-numeric:tabular-nums;color:#3f4c5a}
  .livedemo .mut{color:var(--gray)}
  .livedemo .cap{margin:.6rem 0 0;font-size:.78rem;color:var(--gray);text-align:center}
  /* sections */
  section{padding:3.2rem 0}
  h2{font-size:clamp(1.4rem,3.2vw,1.9rem);color:var(--ink);letter-spacing:-.01em;margin:.2em 0 .45em}
  .lead{font-size:1.1rem;color:#4a5766;max-width:62ch}
  .split{display:grid;grid-template-columns:1fr 1fr;gap:2.6rem;align-items:center}
  /* already in your pocket */
  .pocket{background:var(--bg);border:1px solid var(--line);border-radius:16px;padding:1.4rem 1.6rem}
  .pocket h3{margin:0 0 .5rem;color:var(--ink);font-size:1.08rem}
  .pocket .row{display:flex;gap:.7rem;padding:.5rem 0;align-items:flex-start}
  .pocket .ok{color:var(--green);font-weight:800;flex-shrink:0}
  .pocket .row b{color:var(--ink)}
  .pocket .row .was{display:block;color:var(--gray);font-size:.85rem}
  /* features */
  #features{background:var(--bg);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1.1rem;margin-top:1.5rem}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:1.25rem 1.35rem}
  .card .ic{font-size:1.5rem}
  .card h3{margin:.45rem 0 .3rem;font-size:1.06rem;color:var(--ink)}
  .card p{margin:0;color:#4a5766;font-size:.94rem}
  /* live (merged) */
  #live .livelist{list-style:none;padding:0;margin:1.2rem 0 0;display:grid;gap:.6rem}
  #live .livelist li{display:flex;gap:.6rem;align-items:flex-start;color:#3f4c5a;font-size:1rem}
  #live .livelist .ck{color:var(--green);font-weight:800;flex-shrink:0}
  #live .livenote{margin:1.2rem 0 0;font-style:italic;color:#4a5766;font-size:1rem;
                  border-left:3px solid var(--orange);padding-left:.9rem}
  .trkwrap{background:var(--ink);border-radius:18px;padding:1.2rem 1.2rem 1.4rem;
           box-shadow:0 20px 50px rgba(12,25,41,.30);border:1px solid #1d3149;color:#dce7f2;
           max-width:480px;margin:0 auto}
  .trk-live{display:flex;align-items:center;gap:.5rem;color:var(--orange);font-weight:800;font-size:.92rem}
  .trk-live .dot{width:.65rem;height:.65rem;border-radius:50%;background:var(--green);
                 animation:livepulse 1.1s infinite}
  .trk-clk{font-size:2.3rem;font-weight:800;text-align:center;color:#fff;
           font-variant-numeric:tabular-nums;letter-spacing:1px;margin:.3rem 0 .1rem}
  .trk-wait{text-align:center;color:#7f93a8;font-size:.88rem;border-top:1px solid #1d3149;
            margin-top:.55rem;padding-top:.55rem}
  .trk-strip{display:flex;gap:0;overflow-x:auto;margin:1rem 0 .2rem;padding-bottom:.45rem}
  .trk-ev{flex:0 0 auto;width:72px;text-align:center;position:relative}
  .trk-ev::before{content:"";position:absolute;top:9px;left:-50%;width:100%;height:2px;background:#26405b}
  .trk-ev:first-child::before{display:none}
  .trk-ev i{display:block;width:20px;height:20px;border-radius:50%;margin:0 auto .35rem;
            background:#3a536e;border:3px solid var(--ink);position:relative;z-index:1}
  .trk-ev.done i{background:var(--green)}
  .trk-ev.run i{background:var(--orange);box-shadow:0 0 0 4px rgba(240,100,30,.25)}
  .trk-ev span{font-size:.62rem;line-height:1.15;color:#9fb2c6;display:block}
  .trk-ev.run span{color:var(--orange);font-weight:700}
  .trk-tt{font-weight:800;color:#fff;font-size:.92rem;display:flex;align-items:center;gap:.4rem;margin-top:.5rem}
  .trk-tbl{width:100%;border-collapse:collapse;margin-top:.5rem;font-size:.9rem}
  .trk-tbl th{text-align:left;color:#7f93a8;font-size:.68rem;letter-spacing:.08em;
              text-transform:uppercase;padding:.3rem .2rem}
  .trk-tbl th.pts,.trk-tbl td.pts{text-align:right}
  .trk-tbl td{padding:.45rem .2rem;border-top:1px solid #1d3149}
  .trk-tbl .rk{color:var(--orange);font-weight:800;width:2rem}
  .trk-tbl .pts{font-weight:800;color:#fff;font-variant-numeric:tabular-nums}
  /* coach band */
  .band{background:linear-gradient(135deg,var(--ink2) 0%,var(--ink) 100%);color:#e9eef5}
  .band h2{color:#fff}
  .band .lead{color:#aebdcd}
  .quote{border-left:4px solid var(--orange);padding:.4rem 0 .4rem 1.2rem;margin:1.3rem 0;
         font-size:1.2rem;font-weight:600;color:#fff;max-width:44ch}
  .stat{display:flex;gap:2.2rem;flex-wrap:wrap;margin-top:1.2rem}
  .stat div b{display:block;font-size:2rem;color:var(--orange);line-height:1}
  .stat div span{color:#aebdcd;font-size:.9rem}
  /* fun run */
  #funrun{background:linear-gradient(180deg,#ffffff 0%,#fdf3ea 100%);
          border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  #funrun .frlist{list-style:none;padding:0;margin:1.2rem 0 0;display:grid;gap:.6rem}
  #funrun .frlist li{display:flex;gap:.6rem;align-items:flex-start;color:#3f4c5a;font-size:1rem}
  #funrun .frlist .ck{color:var(--orange);font-weight:800;flex-shrink:0}
  .frcard{background:#fff;border:2px solid #f3d6c1;border-radius:18px;padding:1.4rem 1.5rem;
          box-shadow:0 16px 38px rgba(240,100,30,.16);max-width:340px;margin:0 auto}
  .frcard h3{margin:.1rem 0 .2rem;color:var(--ink);font-size:1.25rem}
  .frcard .sub{margin:0;color:#4a5766;font-size:.95rem}
  .frcard .open{display:inline-flex;align-items:center;gap:.4rem;background:#effaf3;color:#1f7a43;
                border:1px solid #cdeeda;border-radius:999px;padding:.25rem .8rem;
                font-size:.8rem;font-weight:700;margin-bottom:.6rem}
  .frcard .bibrow{display:flex;gap:.5rem;margin-top:.9rem}
  .frcard .bib{background:#fff7f1;border:1px solid #f3d6c1;border-radius:11px;padding:.55rem .3rem;
               text-align:center;flex:1}
  .frcard .bib b{display:block;font-size:1.4rem;color:var(--orange);line-height:1.1}
  .frcard .bib span{font-size:.72rem;color:var(--gray)}
  .frcard .go{margin:.95rem 0 0;font-size:.88rem;color:var(--gray)}
  /* final cta */
  .final{text-align:center}
  .final h2{margin-bottom:.3rem}
  footer{border-top:1px solid var(--line);padding:2rem 0;color:var(--gray);
         font-size:.85rem;text-align:center}
  footer a{color:var(--ink);font-weight:700}
  @media(max-width:860px){
    .hero .wrap,.split{grid-template-columns:1fr;gap:1.8rem}
    section{padding:2.4rem 0}
    header.hero{padding:2.8rem 0 3rem}
  }
</style></head><body>

<nav><div class="wrap">
  <span class="wordmark"><span class="bx">xc</span><span class="bt">t<span class="bi">i</span>mer</span><span class="bd">.com</span></span>
  <a class="signin" href="/login">Sign in</a>
</div></nav>

<header class="hero"><div class="wrap">
  <div>
    <span class="kicker">The do-it-yourself meet manager</span>
    <h1>Run the whole meet yourself.</h1>
    <p class="sub">Rosters, bibs, live timing, field events, scoring, and instant results —
       a junior high or middle school XC or track meet, start to finish, from a phone.
       No timing company. No big invoice.</p>
    <div class="cta">
      <a class="btn" href="#features">See what it does</a>
      <a class="btn ghost" href="mailto:rob@xctimer.com?subject=XCTimer%20for%20our%20district">Get in touch</a>
    </div>
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
      <p class="cap">The live results page every family watches — from the stands or three states away.</p>
    </div>
  </div>
</div></header>

<section id="diff"><div class="wrap split">
  <div>
    <h2>All the equipment you need is already in your pocket.</h2>
    <p class="lead">Timing companies haul in trailers of expensive gear — chip mats, readers,
    cameras, consoles — and bill you for it meet after meet. Your phone already has a camera,
    a clock, and a screen. XCTimer puts them to work, and any coach can run it.</p>
  </div>
  <div class="pocket">
    <h3>📱 One phone replaces all of it</h3>
    <div class="row"><span class="ok">✓</span><div><b>Robot-vision bib reading</b>
      <span class="was">instead of chip mats &amp; readers</span></div></div>
    <div class="row"><span class="ok">✓</span><div><b>Tap-to-time console on the screen</b>
      <span class="was">instead of a trailer of timing gear</span></div></div>
    <div class="row"><span class="ok">✓</span><div><b>Live results the whole crowd follows</b>
      <span class="was">instead of printouts on a fence post</span></div></div>
    <div class="row"><span class="ok">✓</span><div><b>Helpers join with a QR — no accounts</b>
      <span class="was">instead of a hired timing crew</span></div></div>
  </div>
</div></section>

<section id="features"><div class="wrap">
  <h2>Not just timing — the whole meet, start to finish.</h2>
  <p class="lead">Every job you used to hand off, in one tool you run yourself — for cross
     country and track &amp; field.</p>
  <div class="grid">
    <div class="card"><div class="ic">📋</div><h3>AI roster intake &amp; bib stickers</h3>
      <p>Drop in a spreadsheet, PDF, or photo of a roster — AI cleans it up, assigns bibs, and prints Avery stickers.</p></div>
    <div class="card"><div class="ic">⏱️</div><h3>Time it from a phone</h3>
      <p>Tap finishers for cross country, heats &amp; lanes for track — with a no-login QR so helpers can pitch in.</p></div>
    <div class="card"><div class="ic">🤖</div><h3>Robot-vision camera</h3>
      <p>Point a phone at the finish line and bibs read themselves — hands-free timing no other phone can do.</p></div>
    <div class="card"><div class="ic">📏</div><h3>Field events in feet &amp; inches</h3>
      <p>Long Jump and Shot Put with all three attempts, plus a High Jump make/miss grid — the way officials record them.</p></div>
    <div class="card"><div class="ic">🖨️</div><h3>Heat sheets that scan back</h3>
      <p>Print clean heat sheets, mark them up at the event, snap a photo — the marks read straight in.</p></div>
    <div class="card"><div class="ic">🏆</div><h3>Results, scoring &amp; AI insights</h3>
      <p>A public results page with a QR, team scoring by grade &amp; gender, Excel export — and AI answers for PRs and records.</p></div>
  </div>
</div></section>

<section id="live"><div class="wrap split">
  <div>
    <span class="kicker">🟢 Live — everyone's favorite feature</span>
    <h2>The whole crowd follows every race — live.</h2>
    <p class="lead">Share one link or QR and families watch finishers roll in the instant they
    cross — while a live progress bar shows where the meet stands and team scores climb as
    points land. No app, no account.</p>
    <ul class="livelist">
      <li><span class="ck">✓</span> Live race clock, in sync on every phone in the stands</li>
      <li><span class="ck">✓</span> Finishers pop in the moment they're timed</li>
      <li><span class="ck">✓</span> Event-by-event progress bar and climbing team scores</li>
      <li><span class="ck">✓</span> One QR code — hundreds can watch at once</li>
    </ul>
    <p class="livenote">"I spent years in those stands as a parent of three runners — this is the
    feature I always wished I had."</p>
  </div>
  <div>
    <div class="trkwrap">
      <div class="trk-live"><span class="dot"></span> LIVE · 400m Girls 9th Grade · Heat 1</div>
      <div class="trk-clk">0:04:12.8</div>
      <div class="trk-wait">Waiting for the first finisher…</div>
      <div class="trk-strip">
        <div class="trk-ev done"><i></i><span>1600 Boys 9th</span></div>
        <div class="trk-ev done"><i></i><span>100 Girls 7th</span></div>
        <div class="trk-ev done"><i></i><span>100 Girls 8th</span></div>
        <div class="trk-ev done"><i></i><span>400 Girls 8th</span></div>
        <div class="trk-ev run"><i></i><span>400 Girls 9th</span></div>
        <div class="trk-ev"><i></i><span>400 Boys 7th</span></div>
        <div class="trk-ev"><i></i><span>4x100 Girls 7th</span></div>
        <div class="trk-ev"><i></i><span>4x100 Boys 9th</span></div>
      </div>
      <div class="trk-tt">🏆 Overall — team scores</div>
      <table class="trk-tbl">
        <tr><th class="rk">#</th><th>School</th><th class="pts">Points</th></tr>
        <tr><td class="rk">1</td><td>Riverside</td><td class="pts">154</td></tr>
        <tr><td class="rk">2</td><td>Oakmont</td><td class="pts">148</td></tr>
        <tr><td class="rk">3</td><td>Summit Ridge</td><td class="pts">121</td></tr>
      </table>
    </div>
  </div>
</div></section>

<section class="band"><div class="wrap">
  <h2>Built by a coach — and an XC &amp; track parent.</h2>
  <p class="lead">Eight years timing junior-high meets as a coach, and just as many seasons in
  the stands as a parent of three runners. Every feature comes from one of those two seats.</p>
  <div class="quote">"As a coach, I wanted a tool any coach could run. As a parent, I wanted to
  see my kid's race the moment it happened."</div>
  <div class="stat">
    <div><b>8 yrs</b><span>timing meets</span></div>
    <div><b>3 kids</b><span>XC &amp; track athletes</span></div>
    <div><b>1 phone</b><span>is all it takes</span></div>
  </div>
</div></section>

<section id="district"><div class="wrap">
  <span class="kicker">🏫 Districts — better together</span>
  <h2>One platform for the whole district.</h2>
  <p class="lead">When every school hosts on its own timing system, every meet is a fresh
  start — retyped rosters, emailed entry sheets, helpers relearning the tools, and gear bought
  twice. Put the whole district on one platform and each meet gets easier than the last.</p>
  <div class="grid">
    <div class="card"><div class="ic">🗂️</div><h3>One roster, entered once</h3>
      <p>Every school keeps its roster in one place — the host never retypes a visiting team, and bibs print from the same pool at every meet.</p></div>
    <div class="card"><div class="ic">📶</div><h3>Seeded heats from real marks</h3>
      <p>Season bests from every district meet feed the draw — heats seed themselves with real times, not guesses.</p></div>
    <div class="card"><div class="ic">🤝</div><h3>Help that travels</h3>
      <p>Coaches and parent helpers learn one system. At any school's meet, anyone can tap times, scan bibs, or run a pit — no retraining.</p></div>
    <div class="card"><div class="ic">✍️</div><h3>Coaches enter their own athletes</h3>
      <p>Visiting coaches declare their own entries from their phone — no entry sheets emailed to the host the night before.</p></div>
    <div class="card"><div class="ic">🏅</div><h3>District records &amp; season stats</h3>
      <p>PRs, progress cards, season points, and a district record board build automatically across every meet — and AI can answer questions about all of it.</p></div>
    <div class="card"><div class="ic">👨‍👩‍👧</div><h3>One experience for families</h3>
      <p>The same live results page at every meet — parents learn it once and follow every race, all season, at every school.</p></div>
  </div>
  <p style="margin-top:1.6rem"><a class="btn ghost2" href="mailto:rob@xctimer.com?subject=XCTimer%20for%20our%20district">Bring XCTimer to your district</a></p>
</div></section>

<section id="funrun"><div class="wrap split">
  <div>
    <span class="kicker">🏅 New — community events</span>
    <h2>Hosting a fun run or community 5K? Run that yourself, too.</h2>
    <p class="lead">The same engine now powers community races — a fun run, a neighborhood 5K,
    or a 10K &amp; half. Share one link and runners sign themselves up; you just show up and
    start the clock.</p>
    <ul class="frlist">
      <li><span class="ck">✓</span> Public sign-up page + QR — runners enter their own name, age, city &amp; club</li>
      <li><span class="ck">✓</span> Your event's logo and colors on the registration page and printed bibs</li>
      <li><span class="ck">✓</span> Results by gender &amp; age group — bracketed however you like</li>
      <li><span class="ck">✓</span> Phone or robot-vision camera timing, with live results for the crowd</li>
    </ul>
    <a class="btn" href="/host" style="margin-top:1.2rem">🏁 Set up your own fun run</a>
  </div>
  <div>
    <div class="frcard">
      <span class="open">🟢 Registration open</span>
      <h3>Maple Grove Community 5K</h3>
      <p class="sub">Pick your race · grab your bib · no account needed</p>
      <div class="bibrow">
        <div class="bib"><b>5K</b><span>Fun Run</span></div>
        <div class="bib"><b>10K</b><span>Timed</span></div>
        <div class="bib"><b>1&nbsp;mi</b><span>Kids</span></div>
      </div>
      <p class="go">Open the link, register in 20 seconds, from any phone.</p>
    </div>
  </div>
</div></section>

<section class="final"><div class="wrap">
  <h2>Ready to run your own meet?</h2>
  <p class="lead" style="margin:.4rem auto 1.4rem">School meet or community fun run — no timing
     company, no big invoice.</p>
  <div style="display:flex;gap:.8rem;justify-content:center;flex-wrap:wrap">
    <a class="btn" href="/host">🏁 Set up a fun run</a>
    <a class="btn ghost2" href="mailto:rob@xctimer.com?subject=XCTimer%20for%20our%20district">Bring XCTimer to your district</a>
  </div>
</div></section>

<footer>© XCTimer · xctimer.com · the do-it-yourself meet manager for junior high cross country &amp; track
<br><a href="/security">Security &amp; data privacy</a></footer>
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

    # Backstop for db.connect()'s per-request connection registry: whatever a route
    # leaked (crash between write and close) gets closed here, releasing its lock.
    @app.teardown_appcontext
    def _close_leaked_db_conns(exc):
        for c in getattr(g, "_db_conns", None) or []:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    app.before_request(auth.load_principal)
    app.before_request(auth.demo_readonly_guard)

    for bp in (auth_bp, tenancy_bp, schools_bp, meets_bp, xc_bp, track_bp,
               admin_bp, insights_bp, phone_bp, waivers_bp, road_bp):
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
        if request.path == "/square/webhook":   # Square server-to-server call, HMAC-verified instead
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

    @app.get("/welcome")
    def welcome():
        # Always the public marketing page, regardless of any session — "/" redirects a
        # logged-in / phone-timer visitor to their home, so public "Powered by" links
        # (e.g. on results pages, seen by people who also carry a timer session) point here.
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
        # camera=(self): the finish-line camera page (/races/<id>/camera) needs it.
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=(self)")
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
