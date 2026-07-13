"""Shared UI: app shell, CSS, and standalone auth pages (server-rendered).

Vanilla HTML/CSS, no build step (handoff §5). Small helpers keep pages terse.
"""
from markupsafe import escape

BRAND = "XCTimer"

CSS = """
:root{color-scheme:light dark;--bg:#0b1220;--panel:#131c2e;--panel2:#0f1728;
--line:#22314d;--fg:#e7edf5;--mut:#8aa0b6;--dim:#5f7488;--acc:#4f9cf9;--accd:#2f7de0;
--ok:#3fbf7f;--warn:#f0b24b;--err:#f0625b;--radius:12px}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
background:var(--bg);color:var(--fg)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
header.top{display:flex;align-items:center;gap:1rem;padding:.6rem 1rem;
background:var(--panel);border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5}
header.top .brand{font-weight:700;font-size:1.15rem;letter-spacing:-.01em}
header.top .brand .em{margin-right:.35rem}
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
.authcard button{width:100%;margin-top:1rem;padding:.65rem}
.center{text-align:center;margin-top:1rem}
"""

JS = """
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


def shell(principal, body, *, active="", active_district=None, districts=None,
          msg=None, err=None, title=None):
    """Full authenticated page with header, nav, and district switcher."""
    role = principal.role
    nav = []

    def link(href, label, key):
        cls = "on" if active == key else ""
        return f'<a class="{cls}" href="{href}">{escape(label)}</a>'

    nav.append(link("/dashboard", "Dashboard", "dashboard"))
    if role in ("super_admin", "district_admin"):
        nav.append(link("/schools", "Schools", "schools"))
        nav.append(link("/users", "Users", "users"))
    elif role == "coach":
        nav.append(link("/schools", "Roster", "schools"))
    if role in ("super_admin", "district_admin", "coach"):
        nav.append(link("/bibcheck", "Bib check", "bibcheck"))
    if role == "super_admin":
        nav.append(link("/districts", "Districts", "districts"))

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

    head = title or BRAND
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(head)} · {BRAND}</title><style>{CSS}</style></head><body>
<header class="top">
  <div class="brand"><span class="em">🏃</span>{BRAND}</div>
  <nav>{''.join(nav)}</nav>
  <div class="sp"></div>
  {switch}{who}{logout}
</header>
<main>{_flashes(msg, err)}{body}</main>
<script>{JS}</script>
</body></html>"""


def auth_page(title, sub, body, *, msg=None, err=None):
    """Standalone (no-shell) page for login / setup / reset."""
    return f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · {BRAND}</title><style>{CSS}</style></head><body>
<div class="authwrap"><div class="authcard">
  <h1><span>🏃</span> {BRAND}</h1>
  <p class="sub">{escape(sub)}</p>
  {_flashes(msg, err)}
  {body}
</div></div></body></html>"""
