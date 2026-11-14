"""Shared UI: app shell, CSS, and standalone auth pages (server-rendered).

Vanilla HTML/CSS, no build step (handoff §5). Small helpers keep pages terse.
"""
from markupsafe import escape

BRAND = "XCTimer"
# Styled wordmark echoing the logo: orange "xc", light "timer".
BRAND_HTML = '<span class="bx">xc</span><span class="bt">t<span class="bx">i</span>mer</span>'
# Public-page footer "Powered by xctimer" — links to the marketing site. Inline-styled to
# look identical to the plain text (inherits the footer colour, no underline).
POWERED_BY_HTML = ('<a href="https://xctimer.com/welcome" target="_blank" rel="noopener" '
                   'style="color:inherit;text-decoration:none">Powered by '
                   + BRAND_HTML + '</a>')
# The bib sticker we recommend: Avery 5523, the weatherproof version of the 2"x4" 10-up
# sheet every bib PDF is laid out for (Avery 5163) -- it survives rain and sweat.
STICKER_URL = "https://www.amazon.com/dp/B00006IBUW"
STICKER_TIP = ('Best: <a href="' + STICKER_URL + '" target="_blank" rel="noopener">Avery 5523</a> '
               'weatherproof 2"×4" stickers — they hold up to rain and sweat. '
               'Any Avery 5163-size sheet prints too.')
LOGO_URL = "/static/branding/xctimer.png"        # light bg — landing / login card
LOGO_DARK_URL = "/static/branding/xctimerdark.png?v=4"      # UI header (v= busts Cloudflare cache)
LOGO_APP_URL = "/static/branding/xctimerdarkdark.png?v=1"   # phone app
# PWA / home-screen install (clean standalone app on Add to Home Screen).
HEAD_EXTRA = (
    '<link rel="manifest" href="/manifest.webmanifest">'
    '<meta name="theme-color" content="#0a1728">'
    '<meta name="apple-mobile-web-app-capable" content="yes">'
    '<meta name="mobile-web-app-capable" content="yes">'
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
    '<meta name="apple-mobile-web-app-title" content="XCTimer">'
    '<link rel="apple-touch-icon" href="/static/branding/icon-192.png">'
)

# Brand palette sampled from the logo (handoff §11 neutral platform identity):
#   navy #164271 · orange #ea6a2d · gray #868686
CSS = """
:root{color-scheme:light dark;--bg:#0a1728;--panel:#102440;--panel2:#0c1c33;
--line:#213d5c;--fg:#eaf1f8;--mut:#8ea6c0;--dim:#5e7893;
--navy:#164271;--acc:#ea6a2d;--accd:#cf5a22;--link:#6bb0f7;
--ok:#3fbf7f;--warn:#f0b24b;--err:#f0625b;--radius:12px}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--fg)}
a{color:var(--link);text-decoration:none}a:hover{text-decoration:underline}
.bx{color:var(--acc)}.bt{color:var(--fg)}
header.top{display:flex;align-items:center;gap:1rem;padding:.6rem 1rem;
background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header.top .brand{font-weight:800;font-size:1.2rem;letter-spacing:-.02em;display:inline-flex;align-items:center}
header.top .brand .brandchip{display:inline-flex;align-items:center;background:#f4f6f8;border-radius:8px;padding:3px 8px}
header.top .brand .brandchip img{height:26px;width:auto;max-width:160px;object-fit:contain;display:block}
header.top .brand .xclogo{height:48px;width:auto;display:block;border-radius:6px}
header.top nav{display:flex;gap:.25rem;flex-wrap:wrap}
header.top nav a{padding:.35rem .7rem;border-radius:8px;color:var(--mut)}
header.top nav a:hover{background:var(--panel2);color:var(--fg);text-decoration:none}
header.top nav a.on{background:var(--panel2);color:var(--fg)}
header.top .sp{flex:1}
.who{color:var(--mut);font-size:.85rem;text-align:right}
.who b{color:var(--fg)}
.pill{display:inline-block;padding:.05rem .5rem;border:1px solid var(--line);
border-radius:999px;font-size:.72rem;color:var(--mut);text-transform:capitalize}
.dsw{display:flex;align-items:center;gap:.4rem}
.dsw select{background:var(--panel2);color:var(--fg);border:1px solid var(--line);
border-radius:8px;padding:.3rem .5rem;font:inherit}
main{max-width:1000px;margin:0 auto;padding:1.4rem 1rem 4rem}
main.wide{max-width:1340px}
h1{font-size:1.5rem;margin:.2em 0 .1em;letter-spacing:-.01em}
h2{font-size:1.1rem;margin:1.6em 0 .5em;color:var(--fg)}
.sub{color:var(--mut);margin:.1em 0 1.4em}
.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
padding:1.1rem 1.2rem;margin:0 0 1.2rem}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:left;padding:.5rem .6rem;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}
tr:last-child td{border-bottom:0}
label{display:block;font-size:.8rem;color:var(--mut);margin:.6rem 0 .2rem}
input,select,textarea{width:100%;background:var(--panel2);color:var(--fg);
border:1px solid var(--line);border-radius:8px;padding:.5rem .6rem;font:inherit}
.row{display:flex;gap:.8rem;flex-wrap:wrap}.row>div{flex:1;min-width:140px}
button,.btn{background:var(--acc);color:#04101f;border:0;border-radius:8px;
padding:.5rem .9rem;font:inherit;font-weight:600;cursor:pointer}
button:hover,.btn:hover{background:var(--accd);text-decoration:none}
button.ghost,.btn.ghost{background:transparent;color:var(--mut);border:1px solid var(--line)}
button.danger{background:transparent;color:var(--err);border:1px solid var(--line)}
.inline{display:inline}
/* dense admin tables: one line per row, nothing wraps into a tall stack */
table.dense th,table.dense td{padding:.22rem .5rem;white-space:nowrap;vertical-align:middle}
table.dense select,table.dense button,table.dense input{line-height:1.15}
table.dense th{padding-top:.3rem;padding-bottom:.3rem}
/* a wide page is a dense admin page: give the heading block less air */
main.wide h1{margin:.1em 0 .05em}
main.wide .sub{margin:.1em 0 .7em}
main.wide .card{padding:.7rem .8rem}
table.dense td .muted{font-size:.8rem}
table.dense select{width:auto;padding:.15rem .4rem;font-size:.85rem;line-height:1.35}
table.dense button{padding:.18rem .5rem;font-size:.8rem;line-height:1.25}
table.dense .acts{display:flex;gap:.3rem;justify-content:flex-end;align-items:center}
table.dense .acts form{display:inline;margin:0}
table.dense .u-mail{margin-left:.5rem;display:inline-block;max-width:13ch;
overflow:hidden;text-overflow:ellipsis;vertical-align:bottom}
.msg{padding:.6rem .8rem;border-radius:8px;margin:0 0 1rem;font-size:.9rem}
.msg.ok{background:rgba(63,191,127,.12);color:var(--ok);border:1px solid rgba(63,191,127,.3)}
.msg.err{background:rgba(240,98,91,.12);color:var(--err);border:1px solid rgba(240,98,91,.3)}
.msg.warn{background:rgba(240,178,75,.12);color:var(--warn);border:1px solid rgba(240,178,75,.35)}
.muted{color:var(--dim);font-size:.85rem}
.authwrap{min-height:100vh;display:grid;place-items:center;padding:1rem}
.authcard{width:100%;max-width:380px;background:var(--panel);border:1px solid var(--line);
border-radius:16px;padding:2rem}
.authcard h1{text-align:center;margin:.1em 0 .1em}
.authcard .sub{text-align:center;margin-bottom:1.4rem}
.authlogo{margin:0 auto 1.3rem;max-width:250px}
.authlogo img{width:100%;display:block}
.authcard button{width:100%;margin-top:1rem;padding:.65rem}
.center{text-align:center;margin-top:1rem}
/* wide tables scroll inside their card instead of breaking the page */
.card{overflow-x:auto}
@media (max-width:640px){
  header.top{flex-wrap:wrap;gap:.5rem;padding:.5rem .7rem}
  header.top nav{order:3;width:100%;overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch}
  header.top nav a{padding:.35rem .55rem;white-space:nowrap}
  header.top .sp{display:none}
  .who{font-size:.75rem;text-align:left}
  main{padding:1rem .7rem 3rem}
  h1{font-size:1.35rem}
  .card{padding:.9rem}
  table{font-size:.85rem}
  th,td{padding:.4rem .45rem}
  .row>div{min-width:120px}
}
/* Installed home-screen app: lock the chrome to just the brand icon — no way out
   to the rest of the UI, on any page reached inside the app. */
@media all and (display-mode: standalone){
  header.top nav, header.top .who, header.top .dsw, header.top .pill,
  header.top form, header.top .sp{display:none !important}
}
"""

# CSRF (double-submit cookie): the server sets a readable `csrftoken` cookie; every
# mutating request must echo it back. We wrap fetch to add the X-CSRF-Token header on
# all non-GET requests (covers jpost + raw fetch uploads) and auto-inject a hidden
# _csrf field into POST forms — so nothing downstream needs to know about CSRF.
# The animated "LIVE" results card on the marketing pages (/welcome and /start, 1.130.0).
# Any element with data-livedemo that holds a .clk and a <table> becomes a race: the clock
# runs and made-up runners come in at their times, about 10 seconds, once, starting when the
# card scrolls into view, then it rests on the results. Names are invented. With "reduce motion" on, it shows the finished list and stays still.
LIVE_DEMO_JS = r"""
(function(){
  var R=[["Ava Ramirez","Maple",331.4],["Sofia Chen","Ridgeline",333.9],["Harper Diaz","Maple",336.1],
         ["Mia Johnson","Cedar",338.7],["Lily Nguyen","Ridgeline",340.2],["Emma Brooks","Summit",342.8]];
  var T0=330.0, T1=344.5, SPEED=1.4;   // ~10 s; first runner in after ~1 s
  function whenSeen(el,fn){                              // start when the card is on screen
    if(!('IntersectionObserver' in window)) return fn();
    var io=new IntersectionObserver(function(es){ if(es[0].isIntersecting){ io.disconnect(); fn(); } },{threshold:.4});
    io.observe(el);
  }
  var st=document.createElement('style');
  st.textContent='[data-livedemo] tr.ld-new td{animation:ldin .9s ease-out}'+
    '@keyframes ldin{0%{background:rgba(240,100,30,.22);transform:translateY(-6px);opacity:0}'+
    '25%{opacity:1;transform:none}100%{background:transparent}}'+
    '[data-livedemo] .ld-cross{color:#8a96a3;font-style:italic}';
  document.head.appendChild(st);
  function esc(t){return String(t).replace(/[&<>]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;'}[c];});}
  function fmt(t){var m=Math.floor(t/60),s=t-m*60;return m+':'+(s<10?'0':'')+s.toFixed(1);}
  var still=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  [].forEach.call(document.querySelectorAll('[data-livedemo]'),function(box){
    var clk=box.querySelector('.clk'), tbl=box.querySelector('table');
    if(!clk||!tbl) return;
    var rows=R.map(function(){var tr=document.createElement('tr');
      tr.innerHTML='<td class="pl">&nbsp;</td><td>&nbsp;</td><td class="tm"></td>';return tr;});
    tbl.innerHTML=''; var tb=document.createElement('tbody'); tbl.appendChild(tb);
    rows.forEach(function(tr){tb.appendChild(tr);});
    var shown=-1;
    function draw(t){
      clk.textContent=fmt(t);
      var n=0; while(n<R.length && t>=R[n][2]) n++;          // runners in so far
      if(n===shown) return;
      rows.forEach(function(tr,i){
        var c=tr.children;
        if(i<n){
          if(i>=shown || shown<0){                            // just crossed (or first draw)
            c[0].textContent=i+1;
            c[1].innerHTML=esc(R[i][0])+' <span class="mut">· '+esc(R[i][1])+'</span>';
            c[2].textContent=fmt(R[i][2]);
            if(!still && shown>=0){tr.classList.remove('ld-new');void tr.offsetWidth;tr.classList.add('ld-new');}
          }
        }else if(i===n){
          c[0].textContent=i+1; c[1].innerHTML='<span class="ld-cross">… crossing</span>'; c[2].textContent='';
          tr.classList.remove('ld-new');
        }else{
          c[0].innerHTML='&nbsp;'; c[1].innerHTML='&nbsp;'; c[2].textContent=''; tr.classList.remove('ld-new');
        }
      });
      shown=n;
    }
    if(still){ shown=-1; draw(R[R.length-1][2]); return; }
    var start=null;
    function tick(now){                                  // plays once, then rests on the results
      if(start===null) start=now;
      var el=now-start, run=(T1-T0)/SPEED*1000;
      if(el<run){ draw(T0+el/1000*SPEED); requestAnimationFrame(tick); }
      else draw(T1);
    }
    shown=-1; draw(T0);
    whenSeen(box,function(){ requestAnimationFrame(tick); });
  });
})();
"""

# The animated track card on /welcome (1.130.0): two events run back to back, about 15 s,
# once, starting when the card scrolls into view. The clock runs, finishers pop in, the event turns green on the timeline, the timeline
# moves on to the next event, and team points count up (with a lead change). Made-up schools.
# With "reduce motion" on, the card stays as printed.
TRACK_DEMO_JS = r"""
(function(){
  var box=document.querySelector('[data-trackdemo]');
  if(!box || (window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches)) return;
  var EV=["1600 Boys 9th","100 Girls 7th","100 Girls 8th","400 Girls 8th","400 Girls 9th","400 Boys 7th",
          "4x100 Girls 7th","4x100 Boys 9th"];
  var RACES=[
    {ev:4,label:"400m Girls 9th Grade · Heat 1",t0:56,t1:64.0,
     fin:[["Oakmont","Lane 5",62.4],["Riverside","Lane 4",63.1],["Summit Ridge","Lane 3",64.0]]},
    {ev:5,label:"400m Boys 7th Grade · Heat 1",t0:58,t1:66.8,
     fin:[["Oakmont","Lane 4",65.2],["Summit Ridge","Lane 6",65.9],["Riverside","Lane 3",66.8]]}];
  var PTS=[10,8,6], BASE={"Riverside":154,"Oakmont":150,"Summit Ridge":121};
  var SPEED=1.6, SCORE=[1600,2600], COUNT=800;
  var st=document.createElement('style');
  st.textContent='[data-trackdemo] .td-fin{display:flex;justify-content:space-between;gap:.5rem;color:#dce7f2;'+
    'font-size:.86rem;padding:.12rem .1rem;animation:tdin .7s ease-out}'+
    '[data-trackdemo] .td-fin b{color:var(--orange);margin-right:.35rem}'+
    '[data-trackdemo] .td-fin .t{font-variant-numeric:tabular-nums;color:#fff;font-weight:700}'+
    '[data-trackdemo] .td-final{color:var(--green);font-weight:700}'+
    '[data-trackdemo] tr.td-up td{animation:tdflash 1.1s ease-out}'+
    '@keyframes tdin{0%{opacity:0;transform:translateY(-5px);background:rgba(240,100,30,.25)}100%{opacity:1;transform:none;background:transparent}}'+
    '@keyframes tdflash{0%{background:rgba(46,158,91,.35)}100%{background:transparent}}';
  document.head.appendChild(st);
  var hd=box.querySelector('.trk-live'), clk=box.querySelector('.trk-clk'), wait=box.querySelector('.trk-wait'),
      strip=box.querySelector('.trk-strip'), tbl=box.querySelector('.trk-tbl');
  wait.style.minHeight='5.2rem'; wait.style.textAlign='left';
  strip.style.position='relative';                   // so each event's offsetLeft is measured inside the strip
  strip.innerHTML=EV.map(function(e){return '<div class="trk-ev"><i></i><span>'+e+'</span></div>';}).join('');
  var evs=strip.children;
  function f2(n){return (n<10?'0':'')+n;}
  function fmtClk(t){var m=Math.floor(t/60),s=t-m*60;return '0:'+f2(m)+':'+(s<10?'0':'')+s.toFixed(1);}
  function fmtT(t){var m=Math.floor(t/60),s=t-m*60;return m+':'+(s<10?'0':'')+s.toFixed(1);}
  // the phase plan, in ms from the start of a loop; t1 is the last finisher, because the
  // real lane timer stops itself when every lane is tapped
  var plan=[], at=0;
  RACES.forEach(function(r,k){
    var run=(r.t1-r.t0)/SPEED*1000;
    plan.push({k:k,kind:'run',a:at,b:at+run}); at+=run;
    plan.push({k:k,kind:'score',a:at,b:at+SCORE[k]}); at+=SCORE[k];
  });
  var LOOP=at, start=null, last={};
  function totals(k,frac){                       // team points with races < k done, race k at frac
    var t={}; for(var n in BASE) t[n]=BASE[n];
    RACES.forEach(function(r,i){ if(i<k||(i===k&&frac>0)) r.fin.forEach(function(f,j){
      t[f[0]]+=Math.round(PTS[j]*(i<k?1:frac)); }); });
    return t;
  }
  function setStrip(cur,doneCur){
    if(last.strip===cur+'/'+doneCur) return; last.strip=cur+'/'+doneCur;
    for(var i=0;i<evs.length;i++) evs[i].className='trk-ev'+(i<cur||(i===cur&&doneCur)?' done':i===cur?' run':'');
    var el=evs[cur]; strip.scrollTo({left:el.offsetLeft-strip.clientWidth/2+el.offsetWidth/2,behavior:'smooth'});
  }
  function setFin(r,clock,final){
    var n=0; while(n<r.fin.length && clock>=r.fin[n][2]) n++;
    var key=r.ev+'/'+n+'/'+final; if(last.fin===key) return; last.fin=key;
    var h=''; for(var i=0;i<n;i++) h+='<div class="td-fin"><span><b>'+(i+1)+'</b>'+r.fin[i][0]+
      ' <span style="color:#7f93a8">· '+r.fin[i][1]+'</span></span><span class="t">'+fmtT(r.fin[i][2])+'</span></div>';
    if(!n) h='<div style="text-align:center">Waiting for the first finisher…</div>';
    if(final) h+='<div class="td-final" style="text-align:center;margin-top:.2rem">✓ Final · points added</div>';
    wait.innerHTML=h;
  }
  var prevOrder='';
  function setTable(t){
    var names=Object.keys(t).sort(function(a,b){return t[b]-t[a];});
    var order=names.join('|'), rows='<tr><th class="rk">#</th><th>School</th><th class="pts">Points</th></tr>';
    names.forEach(function(n,i){ rows+='<tr data-n="'+n+'"><td class="rk">'+(i+1)+'</td><td>'+n+
      '</td><td class="pts">'+t[n]+'</td></tr>'; });
    var key=order+JSON.stringify(t); if(last.tbl===key) return; last.tbl=key;
    tbl.innerHTML=rows;
    if(prevOrder && order!==prevOrder){                    // someone moved up: flash the new leader row
      var up=tbl.querySelector('tr[data-n="'+names[0]+'"]'); if(up && prevOrder.split('|')[0]!==names[0]) up.className='td-up';
    }
    prevOrder=order;
  }
  function frame(now){                                   // plays once, then rests on the final scores
    if(start===null) start=now;
    var el=now-start, done=el>=LOOP;
    if(done) el=LOOP-1;
    render(el);
    if(!done) requestAnimationFrame(frame);
  }
  function render(el){
    var ph=plan[0];
    for(var i=0;i<plan.length;i++) if(el>=plan[i].a && el<plan[i].b){ph=plan[i];break;}
    var r=RACES[ph.k];
    if(ph.kind==='run'){
      var clock=r.t0+(el-ph.a)/1000*SPEED;
      hd.innerHTML='<span class="dot"></span> LIVE · '+r.label;
      clk.textContent=fmtClk(clock);
      setStrip(r.ev,false); setFin(r,clock,false); setTable(totals(ph.k,0));
    }else{
      hd.innerHTML='<span class="dot"></span> LIVE · '+r.label+' · Final';
      clk.textContent=fmtClk(r.fin[r.fin.length-1][2]);
      setStrip(r.ev,true); setFin(r,r.t1,true);
      setTable(totals(ph.k,Math.min(1,(el-ph.a)/COUNT)));
    }
  }
  render(0);
  if(!('IntersectionObserver' in window)) requestAnimationFrame(frame);
  else { var io=new IntersectionObserver(function(es){ if(es[0].isIntersecting){ io.disconnect(); requestAnimationFrame(frame); } },{threshold:.4}); io.observe(box); }
})();
"""

CSRF_JS = """
(function(){
  function csrf(){ var v=('; '+document.cookie).split('; csrftoken=');
    return v.length===2 ? decodeURIComponent(v.pop().split(';').shift()) : ''; }
  window.__csrf = csrf;
  var _fetch = window.fetch;
  window.fetch = function(input, init){
    init = init || {};
    var m = (init.method || (input && input.method) || 'GET').toUpperCase();
    if(m!=='GET' && m!=='HEAD'){
      var h = new Headers(init.headers || {});
      if(!h.has('X-CSRF-Token')) h.set('X-CSRF-Token', csrf());
      init.headers = h;
    }
    return _fetch(input, init);
  };
  function inject(f){
    if(!f || f.tagName!=='FORM') return;
    if(((f.getAttribute('method')||'get').toLowerCase())!=='post') return;
    var i = f.querySelector('input[name=_csrf]');
    if(!i){ i=document.createElement('input'); i.type='hidden'; i.name='_csrf'; f.appendChild(i); }
    i.value = csrf();
  }
  document.addEventListener('submit', function(e){ inject(e.target); }, true);
  // form.submit() called from JS (e.g. onchange="this.form.submit()") does NOT fire the
  // submit event, so patch it directly — otherwise those POSTs miss the token and 403.
  var _submit = HTMLFormElement.prototype.submit;
  HTMLFormElement.prototype.submit = function(){ inject(this); return _submit.apply(this, arguments); };
})();
"""

JS = CSRF_JS + """
async function jpost(url, data){
  const r = await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(data||{})});
  let j={}; try{j=await r.json()}catch(e){}
  if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
  return j;
}
async function jget(url){const r=await fetch(url);return r.json();}
function esc(s){const d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
"""


def _flashes(msg=None, err=None):
    out = ""
    if err:
        out += f'<div class="msg err">{escape(err)}</div>'
    if msg:
        out += f'<div class="msg ok">{escape(msg)}</div>'
    return out


def home_url(principal):
    """Where the brand/logo and post-login land.

    Coaches start on their Roster: it is the page they actually maintain, and the
    one that has to be right before a meet. Timers have no dashboard and exist to
    run a race, so they still land on Meets; admins get the dashboard.
    """
    if getattr(principal, "meet_scope", None):
        return "/phone"
    role = getattr(principal, "role", None)
    if getattr(principal, "guest", False):
        return "/guest"                 # visiting coach: their team page
    if role == "race_director":
        return "/events"
    if role == "coach":
        return "/schools"          # the coach's "Roster" tab
    return "/meets" if role == "timer" else "/dashboard"


def _brand(principal, href=None, app=False):
    """Top-left brand: district admin -> district logo; coach -> their school logo;
    otherwise the XCTimer mark — xctimerdark on the UI header, xctimerdarkdark in
    the phone app (app=True)."""
    if href is None:
        href = home_url(principal)
    role = getattr(principal, "role", None)
    logo = None
    if role == "district_admin" and getattr(principal, "district_id", None):
        from . import db
        conn = db.connect()
        r = conn.execute("SELECT logo_path FROM districts WHERE id=?",
                         (principal.district_id,)).fetchone()
        conn.close()
        logo = r["logo_path"] if r and r["logo_path"] else None
    elif role == "coach":
        from . import db
        ids = principal.school_ids()
        if ids:
            conn = db.connect()
            r = conn.execute(
                f"SELECT logo_path FROM schools WHERE id IN ({','.join('?' * len(ids))}) "
                f"AND logo_path IS NOT NULL ORDER BY id LIMIT 1", tuple(ids)).fetchone()
            conn.close()
            logo = r["logo_path"] if r else None
    if logo:
        inner = f'<span class="brandchip"><img src="{logo}" alt="XCTimer"></span>'
    else:
        inner = f'<img class="xclogo" src="{LOGO_APP_URL if app else LOGO_DARK_URL}" alt="XCTimer">'
    return f'<a class="brand" href="{href}" style="text-decoration:none">{inner}</a>'


def shell(principal, body, *, active="", active_district=None, districts=None,
          msg=None, err=None, title=None, bare=False, wide=False):
    """Full authenticated page with header, nav, and district switcher.

    bare=True renders only the brand icon in the header (no nav / switcher /
    account / sign-out) — used by the phone timing app so there's no way out to
    the rest of the UI.

    wide=True widens the content column past the usual 1000px, for dense admin
    tables that would otherwise scroll sideways inside their card.
    """
    main_cls = ' class="wide"' if wide else ""
    role = principal.role
    if bare:
        return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title or BRAND)} · {BRAND}</title>{HEAD_EXTRA}<style>{CSS}</style><script>{JS}</script></head><body>
<header class="top">{_brand(principal, "/phone", app=True)}</header>
<main>{_flashes(msg, err)}{body}</main>
<script>{JS}</script>
</body></html>"""
    nav = []

    def link(href, label, key):
        cls = "on" if active == key else ""
        return f'<a class="{cls}" href="{href}">{escape(label)}</a>'

    if getattr(principal, "meet_scope", None):
        nav = []  # meet-day QR principal: minimal chrome, no navigation
    elif getattr(principal, "guest", False):
        # Visiting coach: their team, their roster, the meets they are entered in. Nothing else.
        nav.append(link("/guest", "My team", "guest"))
        nav.append(link("/schools", "Roster", "schools"))
        nav.append(link("/meets", "Meets", "meets"))
    elif role == "race_director":
        # Community race directors live entirely in the Events world — no schools/districts.
        nav.append(link("/events", "Events", "events"))
    else:
        if role in ("super_admin", "district_admin"):
            nav.append(link("/dashboard", "Dashboard", "dashboard"))
        if role == "super_admin":
            nav.append(link("/districts", "Districts", "districts"))
        if role in ("super_admin", "district_admin"):
            nav.append(link("/schools", "Schools", "schools"))
            if not getattr(principal, "is_demo", False):    # shared demo logins never see accounts
                nav.append(link("/users", "Users", "users"))
        if role == "coach":
            nav.append(link("/schools", "Roster", "schools"))
        nav.append(link("/meets", "Meets", "meets"))
        if role in ("super_admin", "district_admin", "coach"):
            nav.append(link("/insights", "Insights", "insights"))
        if role == "super_admin":
            nav.append(link("/organizers", "Organizers", "organizers"))
            nav.append(link("/events", "Events", "events"))
            nav.append(link("/admin/console", "Console", "console"))

    # District switcher (super admin) or fixed label
    switch = ""
    if role == "super_admin" and districts is not None:
        opts = ['<option value="">All districts</option>']
        for d in districts:
            sel = "selected" if active_district == d["id"] else ""
            opts.append(f'<option value="{d["id"]}" {sel}>{escape(d["name"])}</option>')
        switch = (
            '<form class="dsw" method="post" action="/switch-district">'
            '<select name="district_id" onchange="this.form.submit()">'
            + "".join(opts) + "</select></form>"
        )
    elif active_district is not None and districts:
        dname = next((d["name"] for d in districts if d["id"] == active_district), "")
        if dname:
            switch = f'<span class="pill">{escape(dname)}</span>'

    who = (
        f'<div class="who"><b>{escape(principal.name or principal.email or "")}</b>'
        f'<br><span class="pill">{"visiting coach" if getattr(principal, "guest", False) else escape(role.replace("_"," "))}</span></div>'
    )
    logout = ('<form class="inline" method="post" action="/logout">'
              '<button class="ghost" type="submit">Sign out</button></form>')

    # "Ask the Ref" chat: always for the self-serve event owner; also for admins when they're
    # viewing a self-serve (XCTimer Web) event page — so it's not hidden from super admins.
    chat = ""
    show_ref = bool(getattr(principal, "owns_meet", None))
    # A race director who signs in to an organization's Events page runs the same kind of event
    # as a self-serve host, so they get the Ref too (1.113.1) -- it used to be owner-only, which
    # hid it from every event created from the Events page.
    if role == "race_director" and not getattr(principal, "meet_scope", None):
        show_ref = True
    if not show_ref and role in ("super_admin", "district_admin"):
        try:
            import re as _re
            from flask import request as _rq
            mm = _re.match(r"/meets/(\d+)", _rq.path or "")
            if mm:
                from . import db as _db
                c = _db.connect()
                row = c.execute("SELECT 1 FROM meets me JOIN organizers o ON o.id=me.organizer_id "
                                "WHERE me.id=? AND o.slug='xctimer-web'", (int(mm.group(1)),)).fetchone()
                c.close()
                show_ref = bool(row)
        except Exception:
            pass
    if show_ref:
        from .road import host_chat_widget
        chat = host_chat_widget()

    head = title or BRAND
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(head)} · {BRAND}</title>{HEAD_EXTRA}<style>{CSS}</style><script>{JS}</script></head><body>
<header class="top">
  {_brand(principal)}
  <nav>{''.join(nav)}</nav>
  <div class="sp"></div>
  {switch}{who}{logout}
</header>
<main{main_cls}>{_flashes(msg, err)}{body}</main>
{chat}
<script>{JS}</script>
</body></html>"""


def seo_head(path, description=None):
    """<head> tags for a PUBLIC page: its one true address (so "/" and "/welcome", or a link with
    tracking parameters, are not indexed as separate pages) and its own search-result blurb."""
    import os
    base = os.environ.get("XC_PUBLIC_URL", "https://xctimer.com").rstrip("/")
    out = f'<link rel="canonical" href="{base}{path}">'
    if description:
        out += f'\n<meta name="description" content="{escape(description)}">'
    return out


def error_page(code, title, msg):
    """Standalone friendly error page."""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{code} · {BRAND}</title>{HEAD_EXTRA}<style>{CSS}</style></head><body>
<div class="authwrap"><div class="authcard" style="text-align:center">
  <h1>{BRAND_HTML}</h1>
  <p style="font-size:3rem;font-weight:800;margin:.2em 0;color:var(--acc)">{code}</p>
  <p style="font-size:1.1rem;font-weight:600">{escape(title)}</p>
  <p class="sub">{escape(msg)}</p>
  <a class="btn" href="/dashboard" style="display:inline-block;margin-top:.5rem">Back to dashboard</a>
</div></div></body></html>"""


# ---------------------------------------------------------------------------
# Shared "listen for the gun" auto-start control for the running-race timers
# (distance track console + XC/road race timer; sprints have their own copy in
# track._LANE_PAGE). A page drops GUN_CONTROLS_HTML next to its Start button and
# {GUN_JS} inside its <script>, then calls gunReflect(STARTED) in its per-poll UI
# sync. armGun() opens the mic and calls the page's existing startRace() when it
# hears the pistol — so the STARTER's phone sets the shared clock at the true gun
# instant and any FINISHER phone records against that same clock (share the race,
# split the roles). Both host pages already define startRace() and a STARTED flag.
GUN_CONTROLS_HTML = (
    '<button id="gunbtn" type="button" onclick="armGun()" '
    'style="display:block;width:100%;max-width:440px;margin:.5rem auto 0;padding:.8rem;'
    'font-size:1rem;font-weight:700;background:#3d6fa5;color:#fff;border:0;border-radius:12px;'
    'cursor:pointer">\U0001F3A7 Auto-start: listen for the gun</button>'
    '<div id="gunstatus" style="text-align:center;font-size:.85rem;margin-top:.35rem;opacity:.85"></div>'
    '<p id="gunnote" style="text-align:center;font-size:.8rem;opacity:.7;margin:.3rem auto 0;max-width:440px">'
    'Arm this on the <b>starter’s</b> phone at the line. Finishers can time on another phone — '
    'they share the same clock, so there’s no sound-travel delay.</p>'
)

GUN_JS = r"""
var GUNON=false, _gunAC=null, _gunRAF=null;
async function armGun(){
  if(GUNON){disarmGun('');return;}
  if(typeof STARTED!=='undefined' && STARTED)return;
  var st=document.getElementById('gunstatus');
  try{
    var stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});
    _gunAC=new (window.AudioContext||window.webkitAudioContext)();if(_gunAC.state==='suspended')_gunAC.resume();
    var src=_gunAC.createMediaStreamSource(stream),an=_gunAC.createAnalyser();an.fftSize=1024;src.connect(an);
    var buf=new Uint8Array(an.fftSize),armedAt=Date.now();GUNON=true;
    var b=document.getElementById('gunbtn');if(b)b.textContent='🎧 Listening… (tap to cancel)';
    if(st)st.textContent='🎧 Listening for the gun — keep this phone at the start line.';
    (function loop(){
      if(!GUNON)return;
      an.getByteTimeDomainData(buf);
      var peak=0;for(var i=0;i<buf.length;i++){var d=Math.abs(buf[i]-128);if(d>peak)peak=d;}
      if(Date.now()-armedAt>500 && peak>=110){disarmGun('🔫 Gun detected — started!');startRace();return;}
      _gunRAF=requestAnimationFrame(loop);
    })();
  }catch(e){if(st)st.textContent='Mic unavailable — use the Start button.';GUNON=false;}
}
function disarmGun(msg){GUNON=false;if(_gunRAF)cancelAnimationFrame(_gunRAF);try{if(_gunAC)_gunAC.close();}catch(e){}_gunAC=null;
  var b=document.getElementById('gunbtn');if(b)b.textContent='🎧 Auto-start: listen for the gun';
  var st=document.getElementById('gunstatus');if(st&&msg)st.textContent=msg;}
function gunReflect(started){var b=document.getElementById('gunbtn'),n=document.getElementById('gunnote');
  if(b)b.style.display=started?'none':'block'; if(n)n.style.display=started?'none':'block';
  if(started&&GUNON)disarmGun('🔫 Started.');}
"""


def auth_page(title, sub, body, *, msg=None, err=None):
    """Standalone (no-shell) page for login / setup / reset."""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · {BRAND}</title><meta name="robots" content="noindex">{HEAD_EXTRA}<style>{CSS}</style><script>{CSRF_JS}</script></head><body>
<div class="authwrap"><div class="authcard">
  <div class="authlogo"><img src="{LOGO_DARK_URL}" alt="XCTimer"></div>
  <p class="sub">{escape(sub)}</p>
  {_flashes(msg, err)}
  {body}
</div></div></body></html>"""
