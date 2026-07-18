"""Shared UI: app shell, CSS, and standalone auth pages (server-rendered).

Vanilla HTML/CSS, no build step (handoff §5). Small helpers keep pages terse.
"""
from markupsafe import escape

BRAND = "XCTimer"
# Styled wordmark echoing the logo: orange "xc", light "timer".
BRAND_HTML = '<span class="bx">xc</span><span class="bt">timer</span>'
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
.msg{padding:.6rem .8rem;border-radius:8px;margin:0 0 1rem;font-size:.9rem}
.msg.ok{background:rgba(63,191,127,.12);color:var(--ok);border:1px solid rgba(63,191,127,.3)}
.msg.err{background:rgba(240,98,91,.12);color:var(--err);border:1px solid rgba(240,98,91,.3)}
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
    """Where the brand/logo and post-login land: coaches & timers have no
    dashboard, so they go to Meets; admins get the dashboard."""
    if getattr(principal, "meet_scope", None):
        return "/phone"
    role = getattr(principal, "role", None)
    if role == "race_director":
        return "/events"
    return "/meets" if role in ("coach", "timer") else "/dashboard"


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
          msg=None, err=None, title=None, bare=False):
    """Full authenticated page with header, nav, and district switcher.

    bare=True renders only the brand icon in the header (no nav / switcher /
    account / sign-out) — used by the phone timing app so there's no way out to
    the rest of the UI.
    """
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
        f'<br><span class="pill">{escape(role.replace("_"," "))}</span></div>'
    )
    logout = ('<form class="inline" method="post" action="/logout">'
              '<button class="ghost" type="submit">Sign out</button></form>')

    # Self-serve event owners get a floating "Setup help" chat (Claude); nobody else does.
    chat = ""
    if getattr(principal, "owns_meet", None):
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
<main>{_flashes(msg, err)}{body}</main>
{chat}
<script>{JS}</script>
</body></html>"""


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


def auth_page(title, sub, body, *, msg=None, err=None):
    """Standalone (no-shell) page for login / setup / reset."""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · {BRAND}</title>{HEAD_EXTRA}<style>{CSS}</style><script>{CSRF_JS}</script></head><body>
<div class="authwrap"><div class="authcard">
  <div class="authlogo"><img src="{LOGO_DARK_URL}" alt="XCTimer"></div>
  <p class="sub">{escape(sub)}</p>
  {_flashes(msg, err)}
  {body}
</div></div></body></html>"""
