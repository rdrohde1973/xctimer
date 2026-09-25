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
from .coursemap import bp as coursemap_bp

APP_VERSION = "1.105.1-marketing-still-windy"

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
  /* course maps */
  #course{background:var(--bg);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  #course .livelist{list-style:none;padding:0;margin:1.2rem 0 0;display:grid;gap:.6rem}
  #course .livelist li{display:flex;gap:.6rem;align-items:flex-start;color:#3f4c5a;font-size:1rem}
  #course .livelist .ck{color:#38bdf8;font-weight:800;flex-shrink:0}
  .cvd{position:relative;width:290px;height:540px;margin:0 auto;border-radius:34px;overflow:hidden;
       background:#0a1728;border:8px solid #0c1929;
       box-shadow:0 24px 60px rgba(12,25,41,.35),0 0 0 2px #38bdf8}
  .cvd .world{position:absolute;inset:0;width:100%;height:100%;display:block}
  .cvd .top{position:absolute;left:0;right:0;top:0;display:flex;gap:.5rem;align-items:center;
            padding:.7rem .75rem 1.4rem;color:#fff;font-size:.72rem;
            background:linear-gradient(rgba(10,23,40,.85),rgba(10,23,40,0))}
  .cvd .top .bk{background:rgba(255,255,255,.18);border-radius:7px;padding:.25rem .45rem;font-weight:700}
  .cvd .top b{display:block;font-size:.82rem}
  .cvd .toast{position:absolute;left:50%;top:17%;transition:opacity .3s;transform:translateX(-50%);background:rgba(10,23,40,.88);
              color:#fff;font-weight:800;font-size:1.05rem;padding:.35rem .8rem;border-radius:10px}
  .cvd .mi{position:absolute;padding:.12rem .35rem;border-radius:6px;background:#12385f;color:#fff;
           font-size:.62rem;font-weight:800;border:2px solid #fff;transform:translate(-50%,-50%);
           transition:transform .35s cubic-bezier(.2,1.6,.4,1),background .35s}
  .cvd .mi.hit{background:#e8622a;transform:translate(-50%,-50%) scale(1.35)}
  .cvd canvas{position:absolute;inset:0;width:100%;height:100%;display:none}
  .cvd.anim canvas{display:block}
  .cvd.anim .world{display:none}
  .cvd .fl{position:absolute;background:#fff;color:#12385f;font-size:.62rem;font-weight:800;
           padding:.15rem .4rem;border-radius:999px;border:2px solid #111;white-space:nowrap;
           transform:translate(-50%,-125%)}
  .cvd .fl.fin{transform:translate(0,-50%)}
  .cvd .bot{position:absolute;left:0;right:0;bottom:0;padding:1.4rem .75rem .75rem;color:#fff;
            background:linear-gradient(rgba(10,23,40,0),rgba(10,23,40,.92) 30%)}
  .cvd .eh{display:flex;justify-content:space-between;font-size:.6rem;opacity:.9}
  .cvd .elev{display:block;width:100%;height:34px;margin:.25rem 0 .35rem}
  .cvd .dist{font-weight:800;font-size:.8rem}
  .cvd .dist b{font-size:1.15rem}
  .cvd .lg{display:flex;gap:.6rem;font-size:.6rem;margin-top:.2rem}
  .cvd .lg i{display:inline-block;width:14px;height:4px;border-radius:2px;margin-right:.25rem;vertical-align:middle}
  #course .cap{margin:.8rem auto 0;font-size:.78rem;color:var(--gray);text-align:center;max-width:290px}
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

<section id="course"><div class="wrap split">
  <div>
    <div class="cvd" role="img" aria-label="A phone showing a 3D fly-over of a cross-country course: the route drawn over satellite imagery in blue for loop 1 with an orange loop-2 stripe down the middle, the Mile 1 marker lighting up, and an elevation profile along the bottom">
      <img class="world" src="/static/cvd-still.svg?v=1" alt="" width="274" height="524" loading="lazy">
      <canvas id="cvd-canvas" aria-hidden="true"></canvas>
      <div class="top"><span class="bk">‹ Results</span><div><b>Maple Grove Invitational</b>Course map</div></div>
      <div class="toast" id="cvd-toast">🏁 Finish</div>
      <span class="mi hit" id="cvd-mi" style="left:17.0%;top:38.7%">1 mi</span>
      <span class="fl" id="cvd-start" style="left:50.0%;top:29.6%">🟢 Start</span>
      <span class="fl fin" id="cvd-fin" style="left:54.5%;top:70.6%">🏁 Finish</span>
      <div class="bot">
        <div class="eh"><b>Elevation</b><span>↑ 118 ft of climbing</span></div>
        <svg class="elev" viewBox="0 0 300 34" preserveAspectRatio="none" aria-hidden="true">
          <polygon points="0,34 0,26 40,24 70,20 95,12 120,8 150,14 180,22 210,18 240,24 270,26 300,25 300,34" fill="rgba(56,189,248,.35)"/>
          <polyline points="0,26 40,24 70,20 95,12 120,8 150,14 180,22 210,18 240,24 270,26 300,25" fill="none" stroke="#fff" stroke-width="1.5"/>
          <polyline points="70,20 95,12 120,8" fill="none" stroke="#c084fc" stroke-width="3"/>
          <circle id="cvd-edot" cx="300" cy="25" r="3.5" fill="#fff" stroke="#38bdf8" stroke-width="2"/>
        </svg>
        <div class="dist"><b id="cvd-dist">1.42</b> mi · <span id="cvd-km">2.29</span> km</div>
        <div class="lg"><span><i style="background:#38bdf8"></i>Loop 1</span><span><i style="background:#ff6a00"></i>Loop 2</span><span><i style="background:#a855f7"></i>Loop 3</span></div>
      </div>
    </div>
    <p class="cap">The course fly-over, one tap from the results page.</p>
  </div>
  <div>
    <span class="kicker">🗺 New — course maps</span>
    <h2>Fly the course before the gun goes off.</h2>
    <p class="lead">The host traces the course on satellite imagery in a few minutes. Families
    open a 3D fly-over from the results page — over the real hills, every loop in its own colour,
    mile marks lighting up as it passes, and confetti bursting from the finish line.</p>
    <ul class="livelist">
      <li><span class="ck">✓</span> 3D satellite fly-over with real terrain — no app, no account</li>
      <li><span class="ck">✓</span> Each loop in its own colour, mile marks, and a live distance counter</li>
      <li><span class="ck">✓</span> Elevation profile with total climb and the biggest hill called out</li>
      <li><span class="ck">✓</span> Water stations for road races and fun runs</li>
      <li><span class="ck">✓</span> Race-day email to every coach: heat start times, their bib list, and directions to the start line</li>
    </ul>
  </div>
</div></section>
<script>
/* Marketing-page fly-over: the phone mock flies a camera around a little course, drawing
   the route loop by loop (blue, the orange loop-2 stripe, purple), popping the mile marker,
   counting up the distance, then pulls out to the whole course and bursts confetti from the
   finish -- the same beats as the real fly-over, drawn on a canvas in true perspective.
   The static SVG stays underneath as the no-script / reduced-motion picture. */
(function () {
  var box = document.querySelector(".cvd"), cv = document.getElementById("cvd-canvas");
  if (!box || !cv || !cv.getContext) return;
  var ctx = cv.getContext("2d"), W = 274, H = 524, F = 260, NEAR = 2;
  var dpr = Math.min(2, window.devicePixelRatio || 1);
  cv.width = W * dpr; cv.height = H * dpr; ctx.scale(dpr, dpr);
  box.classList.add("anim");
  function $(id) { return document.getElementById(id); }

  // ------------------------------------------------------------------ the scene (metres)
  var patches = [   // [x0, z0, x1, z1, colour]: roads, the school and its lot, a soccer field
    [-160, -14, 160, -9, "#b9b2a4"], [-112, -200, -107, 400, "#b9b2a4"], [-160, 214, 160, 221, "#b9b2a4"],
    [-104, 0, -66, 58, "#9b958a"], [-100, 64, -64, 94, "#d3cdc0"], [-92, 94, -74, 106, "#c6c0b3"],
    [58, 26, 106, 90, "#7fae5e"], [62, 30, 102, 86, "#8bbb69"], [81.5, 30, 82.5, 86, "#e8f0dd"],
    [-150, 130, -118, 205, "#5c8745"], [112, 110, 170, 195, "#668e4d"]];
  var pond = [];
  for (var k = 0; k < 24; k++) { var an = k / 24 * Math.PI * 2; pond.push([16 + Math.cos(an) * 10, 104 + Math.sin(an) * 15]); }
  // The course: a winding loop (smoothed through these points) run twice, then most of a
  // third lap before it breaks off down the finish chute.
  var cps = [[0, 165], [22, 172], [44, 160], [50, 135], [38, 118], [48, 96], [42, 70], [24, 52], [4, 58],
             [-14, 44], [-36, 50], [-46, 74], [-34, 96], [-50, 118], [-44, 146], [-22, 162]];
  function ring(P, per) {                   // closed Catmull-Rom through P
    var out = [], n = P.length;
    for (var q = 0; q < n; q++) {
      var p0 = P[(q - 1 + n) % n], p1 = P[q], p2 = P[(q + 1) % n], p3 = P[(q + 2) % n];
      for (var st = 0; st < per; st++) {
        var t = st / per, t2 = t * t, t3 = t2 * t;
        out.push([0, 1].map(function (ci) {
          return 0.5 * (2 * p1[ci] + (p2[ci] - p0[ci]) * t + (2 * p0[ci] - 5 * p1[ci] + 4 * p2[ci] - p3[ci]) * t2 +
                        (3 * p1[ci] - p0[ci] - 3 * p2[ci] + p3[ci]) * t3);
        }));
      }
    }
    return out;
  }
  var PER = 8, R = ring(cps, PER), lap = R.slice(1).concat([R[0]]);
  // pass = times this ground is covered (stripe width); loop = loop the runner is on (colour)
  var way = [[0, 196]], info = [];
  function add(pts, pass, lp) { pts.forEach(function (p) { info.push([pass, lp]); way.push(p); }); }
  add([R[0]], 1, 1);
  add(lap, 1, 1);
  add(lap, 2, 2);
  add(R.slice(1, 8 * PER + 1), 3, 3);       // round to the near side...
  add([[4, 40], [3, 24]], 1, 3);            // ...and down the chute to the finish
  var START = way[0], FIN = way[way.length - 1];
  // Woods the course runs through, and trees scattered round the park.
  var seed = 11;
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }
  function clear(x, z) {
    for (var q = 0; q < way.length; q++) if (Math.hypot(way[q][0] - x, way[q][1] - z) < 5.5) return false;
    if (Math.hypot(x - 16, (z - 104) / 1.5) < 12) return false;
    for (q = 3; q < 9; q++) { var pt = patches[q]; if (x > pt[0] - 3 && x < pt[2] + 3 && z > pt[1] - 3 && z < pt[3] + 3) return false; }
    return true;
  }
  var trees = [];
  [[47, 130, 13, 34], [-42, 132, 13, 34], [-2, 184, 30, 26], [-26, 74, 9, 12], [0, 118, 10, 8],
   [125, 55, 28, 22], [-135, 40, 16, 18], [60, 205, 45, 22], [-70, 170, 25, 18], [85, 120, 18, 14]].forEach(function (g) {
    for (var q = 0; q < g[3]; q++) {
      var x = g[0] + (rnd() * 2 - 1) * g[2], z = g[1] + (rnd() * 2 - 1) * g[2] * 1.2;
      if (clear(x, z)) trees.push([x, z, 2.2 + rnd() * 1.8, rnd()]);
    }
  });
  var pieces = [], L = 0;
  for (var i = 0; i + 1 < way.length; i++) {
    var a = way[i], b = way[i + 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    var n = Math.max(1, Math.ceil(len / 5));
    for (var j = 0; j < n; j++) {
      var t0 = j / n, t1 = (j + 1) / n;
      pieces.push({ a: [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0],
                    b: [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1],
                    d0: L + len * t0, d1: L + len * t1, pass: info[i][0], loop: info[i][1] });
    }
    L += len;
  }
  var COLOR = [null, "#38bdf8", "#ff6a00", "#a855f7"], WIDTH = [null, 2.6, 1.3, 0.65];
  var MILES = 1.42, MILE_D = L / MILES;
  function at(d) {                          // point + loop at distance d along the route
    d = Math.max(0, Math.min(L, d));
    for (var q = 0; q < pieces.length; q++) {
      var p = pieces[q];
      if (d <= p.d1) { var f = (d - p.d0) / (p.d1 - p.d0 || 1);
        return { x: p.a[0] + (p.b[0] - p.a[0]) * f, z: p.a[1] + (p.b[1] - p.a[1]) * f, loop: p.loop }; }
    }
    var e = pieces[pieces.length - 1];
    return { x: e.b[0], z: e.b[1], loop: e.loop };
  }

  // ------------------------------------------------------------------ camera
  function cam3(x, z, c) {                  // world ground point -> camera space
    var dx = x - c.x, dz = z - c.z, cs = Math.cos(c.yaw), sn = Math.sin(c.yaw);
    var xr = dx * cs - dz * sn, zf = dx * sn + dz * cs;
    var s = Math.sin(c.pitch), co = Math.cos(c.pitch);
    return [xr, -c.h * co + zf * s, c.h * s + zf * co];
  }
  function scr(v, c) { return [W / 2 + F * v[0] / v[2], c.cy - F * v[1] / v[2]]; }
  function proj(x, z, c) { var v = cam3(x, z, c); return v[2] > NEAR ? scr(v, c) : null; }
  function clipSeg(a, b, c) {               // a line on the ground, cut at the near plane
    var A = cam3(a[0], a[1], c), B = cam3(b[0], b[1], c);
    if (A[2] <= NEAR && B[2] <= NEAR) return null;
    if (A[2] <= NEAR || B[2] <= NEAR) {
      var t = (NEAR - A[2]) / (B[2] - A[2]), M = [A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, NEAR + 0.01];
      if (A[2] <= NEAR) A = M; else B = M;
    }
    return [scr(A, c), scr(B, c), (A[2] + B[2]) / 2];
  }
  function quad(p, c) { return shape([[p[0], p[1]], [p[2], p[1]], [p[2], p[3]], [p[0], p[3]]], c); }
  function shape(pts, c) {                  // a flat ground shape, clipped at the near plane
    var vs = pts.map(function (w) { return cam3(w[0], w[1], c); }), m = vs.length;
    var out = [];
    for (var q = 0; q < m; q++) {
      var A = vs[q], B = vs[(q + 1) % m], ai = A[2] > NEAR, bi = B[2] > NEAR;
      if (ai) out.push(A);
      if (ai !== bi) { var t = (NEAR - A[2]) / (B[2] - A[2]);
        out.push([A[0] + (B[0] - A[0]) * t, A[1] + (B[1] - A[1]) * t, NEAR + 0.01]); }
    }
    return out.length > 2 ? out.map(function (v) { return scr(v, c); }) : null;
  }

  // ------------------------------------------------------------------ drawing
  function draw(c, upto, dot) {
    var hz = c.cy - F * Math.tan(c.pitch);
    var sky = ctx.createLinearGradient(0, 0, 0, Math.max(1, hz));
    sky.addColorStop(0, "#3f86d4"); sky.addColorStop(1, "#d6e8f5");
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, Math.max(0, hz) + 1);
    var gr = ctx.createLinearGradient(0, hz, 0, H);
    gr.addColorStop(0, "#9fb58f"); gr.addColorStop(0.25, "#6f9356"); gr.addColorStop(1, "#4b7438");
    ctx.fillStyle = gr; ctx.fillRect(0, hz, W, H - hz);
    function fill(poly, col) {
      if (!poly) return;
      ctx.fillStyle = col; ctx.beginPath(); ctx.moveTo(poly[0][0], poly[0][1]);
      for (var q = 1; q < poly.length; q++) ctx.lineTo(poly[q][0], poly[q][1]);
      ctx.closePath(); ctx.fill();
    }
    patches.forEach(function (p) { fill(quad(p, c), p[4]); });
    fill(shape(pond.map(function (w) { return [16 + (w[0] - 16) * 1.12, 104 + (w[1] - 104) * 1.08]; }), c), "#c9b98f");
    fill(shape(pond, c), "#3f7fa3");
    var haze = ctx.createLinearGradient(0, hz, 0, hz + 40);
    haze.addColorStop(0, "rgba(214,232,245,.9)"); haze.addColorStop(1, "rgba(214,232,245,0)");
    ctx.fillStyle = haze; ctx.fillRect(0, hz, W, 40);
    ctx.lineCap = "round";
    function stroke(p, wm, col, alpha) {
      var b = p.b;
      if (upto < p.d1) { var f = (upto - p.d0) / (p.d1 - p.d0); b = [p.a[0] + (p.b[0] - p.a[0]) * f, p.a[1] + (p.b[1] - p.a[1]) * f]; }
      var s = clipSeg(p.a, b, c);
      if (!s) return;
      ctx.globalAlpha = alpha || 1; ctx.strokeStyle = col; ctx.lineWidth = Math.min(40, F * wm / s[2]);
      ctx.beginPath(); ctx.moveTo(s[0][0], s[0][1]); ctx.lineTo(s[1][0], s[1][1]); ctx.stroke();
    }
    var drawn = pieces.filter(function (p) { return p.d0 < upto; });
    drawn.forEach(function (p) { stroke(p, 3.6, "#263f2c"); });
    [1, 2, 3].forEach(function (ps) { drawn.forEach(function (p) { if (p.pass === ps) stroke(p, WIDTH[ps], COLOR[p.loop]); }); });
    if (dot) {
      drawn.forEach(function (p) {            // comet tail: fades in over the last 25 m
        if (p.d1 > upto - 25) stroke(p, 0.9, "#ffffff", Math.max(0, 1 - (upto - p.d1) / 25) * 0.85);
      });
      ctx.globalAlpha = 1;
    }
    drawTrees(c);
    if (dot) {
      var h = at(upto), s = proj(h.x, h.z, c);
      if (s) {
        ctx.beginPath(); ctx.arc(s[0], s[1], 7, 0, 7); ctx.fillStyle = COLOR[h.loop]; ctx.fill();
        ctx.lineWidth = 3.5; ctx.strokeStyle = "#fff"; ctx.stroke();
      }
    }
    ctx.globalAlpha = 1;
  }
  function drawTrees(c) {                   // far to near, fading out as the camera flies through
    var list = [], co = Math.cos(c.pitch);
    trees.forEach(function (t) { var v = cam3(t[0], t[1], c); if (v[2] > 8) list.push([v, t]); });
    list.sort(function (p, q) { return q[0][2] - p[0][2]; });
    list.forEach(function (e) {
      var v = e[0], t = e[1], s = scr(v, c), r = F * t[2] / v[2], ht = F * t[2] * 1.5 / v[2] * co;
      if (r < 0.5 || s[0] < -2 * r || s[0] > W + 2 * r || s[1] < -r) return;
      ctx.globalAlpha = Math.max(0, Math.min(1, (v[2] - 10) / 14));
      ctx.fillStyle = "rgba(15,35,15,.3)";
      ctx.beginPath(); ctx.ellipse(s[0] + r * 0.4, s[1], r * 1.05, r * 0.42, 0, 0, 7); ctx.fill();
      ctx.strokeStyle = "#5b4630"; ctx.lineWidth = Math.max(1, r * 0.22);
      ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(s[0], s[1] - ht * 0.5); ctx.stroke();
      var cy2 = s[1] - ht * 0.5 - r * 0.55;
      ctx.fillStyle = t[3] > 0.5 ? "#2e5b29" : "#386a2f";
      ctx.beginPath(); ctx.arc(s[0], cy2, r, 0, 7); ctx.fill();
      ctx.fillStyle = "rgba(130,180,95,.5)";
      ctx.beginPath(); ctx.arc(s[0] - r * 0.3, cy2 - r * 0.3, r * 0.5, 0, 7); ctx.fill();
    });
    ctx.globalAlpha = 1;
  }
  function place(el, x, z, c) {
    var s = proj(x, z, c);
    if (!s || s[0] < -30 || s[0] > W + 30 || s[1] < 50 || s[1] > H - 120) { el.style.visibility = "hidden"; return; }
    el.style.visibility = "visible";
    el.style.left = (s[0] / W * 100) + "%"; el.style.top = (s[1] / H * 100) + "%";
  }

  // ------------------------------------------------------------------ the show
  var OVER = { x: 0, z: -10, h: 62, pitch: 34 * Math.PI / 180, yaw: 0, cy: 236 };
  var INTRO = 1200, FLY = 19000, OUTRO = 2600, HOLD = 3400, CYCLE = INTRO + FLY + OUTRO + HOLD;
  var mileAt = at(MILE_D), yawS = 0, lastT = 0, lastLoop = 1, milePopped = false, toastTimer = 0;
  var eh = [[0, 26], [40, 24], [70, 20], [95, 12], [120, 8], [150, 14], [180, 22], [210, 18], [240, 24], [270, 26], [300, 25]];
  function toast(t) {
    var el = $("cvd-toast"); el.textContent = t; el.style.opacity = 1;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { el.style.opacity = 0; }, 1300);
  }
  function heading(d) { var a = at(d - 8), b = at(d + 25); return Math.atan2(b.x - a.x, b.z - a.z); }
  function follow(d) {
    var p = at(d);
    return { x: p.x - Math.sin(yawS) * 34, z: p.z - Math.cos(yawS) * 34, h: 20, pitch: 0.5, yaw: yawS, cy: 300 };
  }
  function turnTo(target, k) { var df = ((target - yawS + 3 * Math.PI) % (2 * Math.PI)) - Math.PI; yawS += df * k; }
  function ease(u) { return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2; }
  function mix(A, B, u) {
    var dy = ((B.yaw - A.yaw + 3 * Math.PI) % (2 * Math.PI)) - Math.PI, o = {};
    ["x", "z", "h", "pitch", "cy"].forEach(function (key) { o[key] = A[key] + (B[key] - A[key]) * u; });
    o.yaw = A.yaw + dy * u; return o;
  }
  function hud(d) {
    var u = d / L;
    $("cvd-dist").textContent = (u * MILES).toFixed(2);
    $("cvd-km").textContent = (u * MILES * 1.609344).toFixed(2);
    var x = u * 300, y = 26;
    for (var q = 0; q + 1 < eh.length; q++) if (x <= eh[q + 1][0]) { y = eh[q][1] + (eh[q + 1][1] - eh[q][1]) * (x - eh[q][0]) / (eh[q + 1][0] - eh[q][0]); break; }
    $("cvd-edot").setAttribute("cx", x.toFixed(1)); $("cvd-edot").setAttribute("cy", y.toFixed(1));
  }
  function labels(c) {
    place($("cvd-start"), START[0], START[1], c); place($("cvd-fin"), FIN[0], FIN[1], c); place($("cvd-mi"), mileAt.x, mileAt.z, c);
  }

  // confetti bursting out of the finish line
  var bits = [], CONF = ["#ffd400", "#ff7a00", "#ff2d95", "#22d3ee", "#7CFC00", "#ffffff"];
  function burst(x, y) {
    for (var q = 0; q < 120; q++) {
      var ang = Math.random() * Math.PI * 2, sp = 2 + Math.random() * 5.5;
      bits.push({ x: x, y: y, vx: Math.cos(ang) * sp, vy: Math.sin(ang) * sp - 2.5, r: Math.random() * 6, vr: Math.random() * 0.4 - 0.2,
                  c: CONF[q % CONF.length], life: 1 });
    }
  }
  function confetti() {
    bits = bits.filter(function (b) { return b.life > 0 && b.y < H + 10; });
    bits.forEach(function (b) {
      b.vy += 0.16; b.vx *= 0.985; b.x += b.vx; b.y += b.vy; b.r += b.vr; b.life -= 0.006;
      ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.r); ctx.globalAlpha = Math.max(0, Math.min(1, b.life * 1.5));
      ctx.fillStyle = b.c; ctx.fillRect(-3, -1.8, 6, 3.6); ctx.restore();
    });
    ctx.globalAlpha = 1;
  }

  var t0 = null, burstDone = false, lastCyc = -1;
  function frame(now) {
    if (t0 === null) { t0 = now; lastT = now; }
    var dt = Math.min(0.05, (now - lastT) / 1000); lastT = now;
    var t = (now - t0) % CYCLE, cyc = Math.floor((now - t0) / CYCLE), c, d, dot = true;
    if (cyc !== lastCyc) { lastCyc = cyc; yawS = heading(0); lastLoop = 1; milePopped = false; burstDone = false; bits = [];
                  $("cvd-mi").classList.remove("hit"); toast("🟢 Start"); }
    if (t < INTRO) { d = 0; c = follow(0); }
    else if (t < INTRO + FLY) {
      d = (t - INTRO) / FLY * L;
      turnTo(heading(d), Math.min(1, dt * 3.2)); c = follow(d);
      var lp = at(d).loop;
      if (lp > lastLoop) { lastLoop = lp; toast("Loop " + lp); }
      if (!milePopped && d >= MILE_D) { milePopped = true; $("cvd-mi").classList.add("hit"); toast("Mile 1"); }
    } else {
      d = L; dot = t < INTRO + FLY + OUTRO;
      var u = Math.min(1, (t - INTRO - FLY) / OUTRO);
      c = mix(follow(L), OVER, ease(u));
      if (u >= 1 && !burstDone) { burstDone = true; toast("🏁 Finish"); var s = proj(FIN[0], FIN[1], c); if (s) burst(s[0], s[1] - 10); }
    }
    ctx.clearRect(0, 0, W, H);
    draw(c, d, dot);
    confetti();
    labels(c);
    hud(d);
    if (running) raf = requestAnimationFrame(frame);
  }

  var running = false, raf = 0;
  function start() { if (running) return; running = true; lastT = performance.now(); t0 = null; lastCyc = -1; raf = requestAnimationFrame(frame); }
  function stop() { running = false; cancelAnimationFrame(raf); }
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduce) {                             // one still frame: the whole course, no motion
    draw(OVER, L, false); labels(OVER); hud(L); $("cvd-mi").classList.add("hit"); $("cvd-toast").style.opacity = 0;
    return;
  }
  // Only animate while it's on screen.
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(function (es) { es[0].isIntersecting ? start() : stop(); }, { threshold: 0.2 }).observe(box);
  } else start();
})();
</script>


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
               admin_bp, insights_bp, phone_bp, waivers_bp, road_bp, coursemap_bp):
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
        # Static files: cacheable by Cloudflare and browsers, and never carrying a cookie --
        # Cloudflare will not cache a response that sets one, so every parent opening the
        # course fly-over used to pull the 1 MB map library from this server.
        if request.path.startswith("/static/"):
            if request.args.get("v"):            # stamped with the file time: safe forever
                resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            elif request.path.startswith("/static/vendor/"):
                resp.headers["Cache-Control"] = "public, max-age=86400"
            else:                                 # unstamped: short, so deploys show up fast
                resp.headers["Cache-Control"] = "public, max-age=300"
            resp.headers.pop("Pragma", None)
            return resp
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
