"""Self-serve sign-up for schools (1.113.0): xctimer.com/start.

A coach fills in one short form and gets, with nobody at XCTimer involved:

  * a district of their own, tagged Pay per meet (billing.py), holding
  * their school, and
  * a COACH login for themselves, linked to that school, set up from an emailed link (which is
    also what proves the address is theirs).

District admins exist only in districts on the paid subscription (Rob, 2026-11-12), so a
self-serve school gets a coach and nothing more. A coach can keep the roster, create and pay
for meets hosted at the school, and invite visiting teams; adding schools or users is done by
XCTimer, or by a district admin once the district subscribes.

Nothing here costs XCTimer anything: the meet they build cannot be timed until the $100
meet fee is paid or a promo code is entered. Every sign-up emails the operator, so each one
is a lead -- including the ones that belong in a district subscription instead.

A sign-up never joins an existing district because the NAME matches: that would show another
school's roster to whoever typed the name. The operator email points out a likely match so the
two can be merged by hand.

Joining by email domain (1.118.0, Rob 2026-11-13). A district can carry its email domain(s) in
settings_json["email_domains"] -- set by Super Admin on the Districts page, and recorded
automatically when a self-serve district is created from a non-public address. When a new
sign-up's address is at exactly that domain:

  * the school is added to that district instead of a new district being made, or
  * if the school looks like one already there, the coach is shown it and asked to confirm,
    and is then added as a coach of the existing school.

What keeps this safe is the same thing that proves any sign-up: the login only works from the
link emailed to that address, so only someone with a mailbox at the district's domain gets in.
Public mail providers (gmail.com and friends) never match and are never recorded. A domain
claimed by two districts matches neither. Every join emails the operator.
"""
import difflib
import json
import logging
import os
import re
import time
from html import escape

from flask import Blueprint, g, make_response, redirect, request

from . import db, billing
from .auth import create_user, find_user_by_email, issue_reset_token, send_email, _public_url, _iso, _now
from .ui import HEAD_EXTRA, CSRF_JS, LIVE_DEMO_JS, seo_head

bp = Blueprint("signup", __name__)
log = logging.getLogger("xctimer.signup")

LEVELS = {                      # form value -> (label, district grade list or None for the default 6-9)
    "ms": ("Middle school / junior high", None),
    "hs": ("High school", [9, 10, 11, 12]),
    "both": ("Both (grades 6-12)", [6, 7, 8, 9, 10, 11, 12]),
}
_HITS = {}                      # (bucket, ip) -> [timestamps]; a small in-memory brake on scripted sign-ups
_MAX_PER_HOUR = 5               # sign-ups (anything that creates a row or sends an email)
_MAX_LOOKUPS = 30               # "is this your school?" pages, which create and send nothing

# Mail providers anyone can get an address at: never a district's own domain.
PUBLIC_DOMAINS = frozenset("""
gmail.com googlemail.com yahoo.com ymail.com rocketmail.com yahoo.co.uk yahoo.ca hotmail.com
hotmail.co.uk outlook.com live.com msn.com icloud.com me.com mac.com aol.com aim.com
proton.me protonmail.com pm.me gmx.com gmx.net mail.com zoho.com hey.com fastmail.com
fastmail.fm tutanota.com tuta.io yandex.com duck.com comcast.net xfinity.com att.net
sbcglobal.net bellsouth.net verizon.net cox.net charter.net spectrum.net twc.com rr.com
roadrunner.com centurylink.net q.com frontier.com frontiernet.net windstream.net
earthlink.net juno.com netzero.net optonline.net optimum.net suddenlink.net mediacombb.net
cableone.net sparklight.net tds.net embarqmail.com shaw.ca rogers.com bell.net telus.net
sympatico.ca btinternet.com sky.com qq.com 163.com mail.ru
""".split())


def _throttled(ip, bucket="signup", limit=_MAX_PER_HOUR):
    now = time.time()
    key = (bucket, ip)
    hits = [t for t in _HITS.get(key, []) if now - t < 3600]
    if len(hits) >= limit:
        _HITS[key] = hits
        return True
    hits.append(now)
    _HITS[key] = hits
    return False


# ------------------------------- joining a district by email domain -------------------------------
def parse_domains(text):
    """'@Alpine District.org, foo.k12.ut.us' -> ['alpinedistrict.org', ...]; junk and public
    mail providers are dropped."""
    out = []
    for raw in re.split(r"[\s,;]+", (text or "").lower()):
        d = raw.strip().lstrip("@").strip(".")
        if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", d) and d not in PUBLIC_DOMAINS and d not in out:
            out.append(d)
    return out[:5]


def email_domains(settings_json):
    try:
        v = json.loads(settings_json or "{}").get("email_domains") or []
    except (ValueError, TypeError):
        return []
    return [d for d in v if isinstance(d, str)]


def districts_claiming(conn, domain):
    if not domain or domain in PUBLIC_DOMAINS:
        return []
    return [d for d in conn.execute("SELECT id, name, settings_json FROM districts ORDER BY id").fetchall()
            if domain in email_domains(d["settings_json"])]


def district_for_domain(conn, domain):
    """The one district whose email domain is exactly `domain`, else None (two claims = none)."""
    hits = districts_claiming(conn, domain)
    return hits[0] if len(hits) == 1 else None


_LEVEL_WORDS = {"middle", "junior", "jr", "high", "senior", "sr", "school", "schools", "ms", "jhs",
                "jh", "hs", "intermediate", "the"}


def _core(name):
    """'Lehi Jr. High School' -> 'lehi': the part of a school name people actually type."""
    toks = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower().replace("&", " and ")).split()
    return " ".join([t for t in toks if t not in _LEVEL_WORDS] or toks)


def _looks_like(a, b):
    """Score 0..3 for how alike two school names are (0 = not alike)."""
    a, b = _core(a), _core(b)
    if not a or not b:
        return 0
    if a == b:
        return 3
    if min(len(a), len(b)) >= 4 and (a.startswith(b + " ") or b.startswith(a + " ")):
        return 2
    initials = lambda s: "".join(t[0] for t in s.split())                    # noqa: E731
    if (len(a) >= 2 and " " in b and initials(b) == a) or (len(b) >= 2 and " " in a and initials(a) == b):
        return 2                                                             # "AF" ~ "American Fork"
    return 1 if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85 else 0


def matching_schools(conn, did, name):
    """Schools already in the district that look like the one typed, best match first."""
    rows = conn.execute("SELECT id, name FROM schools WHERE district_id=? AND COALESCE(guest,0)=0 "
                        "ORDER BY name", (did,)).fetchall()
    scored = [(_looks_like(name, r["name"]), r) for r in rows]
    return [r for sc, r in sorted(scored, key=lambda x: -x[0]) if sc][:4]


def _ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "-")


def _clean(v, n=80):
    return " ".join("".join(ch for ch in (v or "") if ch.isprintable()).split())[:n]


def _slug(conn, name):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "school"
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM districts WHERE slug=?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def is_self_serve(settings_json):
    try:
        return bool(json.loads(settings_json or "{}").get("self_serve"))
    except (ValueError, TypeError):
        return False


# ------------------------------- pages -------------------------------
def _page(title, inner, head=""):
    return (f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · XCTimer</title>{head}{HEAD_EXTRA}<script>{CSRF_JS}</script>
<style>body{{font:16px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;background:#f5f8fc;color:#20303f;margin:0}}
.wrap{{max-width:560px;margin:0 auto;padding:1.4rem 1.1rem 3rem}}
.card{{background:#fff;border:1px solid #e3e9f1;border-radius:12px;padding:1.1rem;margin:0 0 1rem}}
label{{display:block;font-weight:600;margin:.7rem 0 .2rem}} .opt{{font-weight:400;color:#6a7c8e}}
input,select,button{{font:inherit}}
input,select{{width:100%;padding:.55rem;border:1px solid #cdd7e2;border-radius:8px;background:#fff;box-sizing:border-box}}
.btn{{background:#ea6a2d;color:#fff;border:0;border-radius:9px;padding:.7rem 1.3rem;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}}
.fine{{font-size:.85rem;color:#6a7c8e}} .err{{color:#b3261e;font-weight:600}}
.hp{{position:absolute;left:-9999px;top:auto;width:1px;height:1px;overflow:hidden}}
h1{{color:#164271;margin-top:0}} a{{color:#164271}}</style></head><body><div class="wrap">
<p><a href="/welcome">← XCTimer</a> · <a href="/pricing">Pricing</a></p>{inner}</div></body></html>""")


_PREVIEW_CSS = """<style>
.hero h1{font-size:1.75rem;line-height:1.2;margin:.2rem 0 .5rem}
.hero .sub{font-size:1.05rem;color:#43586c;margin:0 0 1rem}
.live{background:#fff;border:2px solid #ea6a2d;border-radius:14px;padding:.9rem 1rem;margin:0 0 1rem;
      box-shadow:0 8px 24px rgba(22,66,113,.10)}
.live .hd{display:flex;align-items:center;gap:.45rem;font-weight:800;color:#ea6a2d;font-size:.9rem}
.live .dot{width:.6rem;height:.6rem;border-radius:50%;background:#2e9e5b;animation:pulse 1.4s infinite}
@keyframes pulse{50%{opacity:.35}}
.live .clk{font-size:2.3rem;font-weight:800;text-align:center;color:#164271;font-variant-numeric:tabular-nums;margin:.2rem 0}
.live table{width:100%;border-collapse:collapse;font-size:.95rem}
.live td{padding:.3rem .2rem;border-top:1px solid #edf1f6}
.live .pl{color:#ea6a2d;font-weight:800;width:1.4rem} .live .tm{text-align:right;font-variant-numeric:tabular-nums}
.live .mut{color:#6a7c8e} .live .cap{font-size:.85rem;color:#6a7c8e;margin:.5rem 0 0}
.pts{list-style:none;padding:0;margin:0 0 1rem}
.pts li{display:flex;gap:.6rem;margin:.55rem 0;font-size:1rem}
.pts li b{color:#164271} .pts .ck{color:#2e9e5b;font-weight:800}
.season{background:#eef5ff;border-radius:10px;padding:.7rem .9rem;margin:0 0 1rem;font-size:.97rem}
</style>"""

# The /start funnel (1.126.0): which steps a visitor reaches, recorded once per browser per step
# by POST /start/step (audit.note_start_step). It answers "do people leave before or after they
# start the form?" -- nothing typed into the form is ever sent.
_FUNNEL_JS = """<script>
(function(){
  var sent={};
  function step(s){ if(sent[s]) return; sent[s]=1;
    try{ fetch('/start/step',{method:'POST',keepalive:true,
      headers:{'Content-Type':'application/json'},body:JSON.stringify({step:s})}); }catch(e){} }
  step('view');
  var card=document.getElementById('create');
  if(card && 'IntersectionObserver' in window){
    new IntersectionObserver(function(es,o){ es.forEach(function(e){
      if(e.isIntersecting){ step('form'); o.disconnect(); } }); },{threshold:.5}).observe(card);
  }
  if(card){
    card.addEventListener('focusin',function(){ step('typing'); });
    var f=card.querySelector('form'); if(f) f.addEventListener('submit',function(){ step('submit'); });
  }
  var more=document.getElementById('more'); if(more) more.addEventListener('click',function(){ step('more'); });
})();
</script>"""


def _form(err="", v=None):
    v = v or {}
    val = lambda k: escape(v.get(k, ""))                                   # noqa: E731
    fee = billing.fee_str()
    errp = f'<p class="err">{escape(err)}</p>' if err else ""
    # Short form (1.126.0): school and email only. Name, level, state and district are asked
    # on the password page the emailed link opens (setup_extra below), once they are invested.
    return _page("Cross country and track meet timing for your school", f"""<div class="hero">
<h1>Run your own cross country and track meets from a phone.</h1>
<p class="sub">Rosters, bibs, heats, phone timing and live results. No timing company and no chip mats.</p>
</div>
<div class="live" data-livedemo aria-label="Example of a live results page">
  <div class="hd"><span class="dot"></span> LIVE · Girls 7th Grade 1600m</div>
  <div class="clk">5:38.2</div>
  <table>
    <tr><td class="pl">1</td><td>Ava Ramirez <span class="mut">· Maple</span></td><td class="tm">5:31.4</td></tr>
    <tr><td class="pl">2</td><td>Sofia Chen <span class="mut">· Ridgeline</span></td><td class="tm">5:33.9</td></tr>
    <tr><td class="pl">3</td><td>Harper Diaz <span class="mut">· Maple</span></td><td class="tm">5:36.1</td></tr>
    <tr><td class="pl">4</td><td class="mut">… crossing</td><td class="tm"></td></tr>
  </table>
  <p class="cap">Example of the live results page families follow from the stands.</p>
</div>
<script>{LIVE_DEMO_JS}</script>
<ul class="pts">
<li><span class="ck">✓</span><span><b>Time it on phones.</b> One helper taps each finisher; the phone camera reads the bibs.</span></li>
<li><span class="ck">✓</span><span><b>Results post themselves,</b> with team scores, on a live page anyone can open.</span></li>
<li><span class="ck">✓</span><span><b>Build everything free.</b> It is {fee} only when a meet goes live.</span></li>
</ul>
<p class="season">Getting ready for next season? Set your school up free now, and your roster and meets
are ready when you are.</p>
<div class="card" id="create">{errp}<h2 style="margin:0 0 .2rem;color:#164271">Set up your school</h2>
<form method="post" action="/start">
<label>School name</label><input name="school" required maxlength="80" value="{val('school')}" placeholder="e.g. Maple Grove High School">
<label>Your email</label><input name="email" type="email" required maxlength="120" value="{val('email')}" autocomplete="email">
<div class="hp" aria-hidden="true"><label>Website</label><input name="website" tabindex="-1" autocomplete="off"></div>
<p class="fine">We email you a private link to finish setting up. Use your school email if you have one.</p>
<button class="btn" type="submit">Create my school →</button>
<p class="fine" style="margin:.7rem 0 0">By signing up you confirm your school lets you manage its team roster.
See <a href="/security">Security &amp; data privacy</a>.</p>
</form></div>
<p style="margin:0 0 1rem"><a id="more" href="/welcome#features">See everything XCTimer does →</a></p>
<div class="card"><h2 style="margin-top:0">How it works</h2><ol style="padding-left:1.2rem;margin:0">
<li>Tell us your school and email. We send you a private link.</li>
<li>Import your roster, then build a meet: events, entries, heats, bibs and heat sheets.</li>
<li>Invite visiting teams with a link. They enter their own athletes, free.</li>
<li>Pay {fee} by card when you are ready to time it, or enter a promo code.</li></ol></div>
<div class="card"><b>Several schools in one district?</b> A district subscription is {fee} per school per
season with unlimited meets, shared rosters, AI Insights and priority support.
<a href="mailto:rob@xctimer.com?subject=XCTimer%20for%20our%20district">Get in touch</a> or
<a href="/pricing">see pricing</a>.</div>
<p class="fine">Hosting a fun run or community 5K instead? <a href="/host">Set that up here</a>.
Already have an account? <a href="/login">Sign in</a>.</p>{_FUNNEL_JS}""",
                 head=seo_head("/start", f"Set up your school on XCTimer: rosters, bibs, heats, phone timing "
                                         f"and live results for cross country and track meets. Free to "
                                         f"build, {fee} when a meet goes live.") + _PREVIEW_CSS)


def _sent(email):
    return _page("Check your email",
                 f'<div class="card"><h1>✅ Check your email</h1><p>We emailed <b>{escape(email)}</b> a private '
                 f'link to finish setting up. It comes from <b>XCTimer</b> and works for 7 days.</p>'
                 f'<p>Check your spam folder if it doesn’t arrive in a few minutes. Wrong address? '
                 f'<a href="/start">Go back</a>.</p></div>')


def _confirm(f, district, cands):
    """The district is already here and a school in it looks like theirs: ask, do not guess."""
    hidden = "".join(f'<input type="hidden" name="{k}" value="{escape(f.get(k, ""))}">'
                     for k in ("school", "district", "state", "who", "email", "level"))
    yes = "".join(f'<button class="btn" style="display:block;width:100%;margin:.5rem 0;text-align:left" '
                  f'name="match" value="{c["id"]}" type="submit">Yes, I coach at {escape(c["name"])}</button>'
                  for c in cands)
    one = len(cands) == 1
    return _page("Is this your school?", f"""<h1>Is this your school?</h1>
<div class="card"><p><b>{escape(district["name"])}</b> already uses XCTimer, and
{"a school there looks" if one else "these schools there look"} like <b>{escape(f["school"])}</b>.</p>
<form method="post" action="/start">{hidden}{yes}
<button class="btn" style="display:block;width:100%;margin:.5rem 0;text-align:left;background:#fff;color:#164271;border:1px solid #cdd7e2"
 name="match" value="new" type="submit">No, add {escape(f["school"])} as a new school</button>
<p class="fine" style="margin:.8rem 0 0">Either way we email <b>{escape(f["email"])}</b> a private link to
finish. Choosing your existing school adds you as one of its coaches, with its roster and meets.</p>
</form></div><p class="fine"><a href="/start">← Start over</a></p>""")


@bp.get("/start")
def start():
    if getattr(g, "principal", None) and not getattr(g.principal, "meet_scope", None):
        from .ui import home_url
        return redirect(home_url(g.principal))
    from .road import capture_attribution
    return capture_attribution(make_response(_form()))


@bp.post("/start/step")
def start_step():
    """The /start funnel beacon (see _FUNNEL_JS). Always 204: it must never show an error."""
    from . import audit
    audit.note_start_step(str((request.get_json(silent=True) or {}).get("step", ""))[:12])
    return "", 204


@bp.post("/start")
def create():
    f = {k: _clean(request.form.get(k)) for k in ("school", "district", "state", "who")}
    f["email"] = _clean(request.form.get("email"), 120).lower()
    f["level"] = request.form.get("level") if request.form.get("level") in LEVELS else "ms"
    if request.form.get("website"):                  # honeypot: a person never sees this field
        return _sent(f["email"] or "you")
    if not f["school"] or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
        return _form("Please enter your school and a valid email.", f), 400
    too_many = (_form("Too many sign-ups from this network. Please try again in an hour, "
                      "or email rob@xctimer.com.", f), 429)

    # Is their district already here? Only an exact email-domain match counts (see the docstring).
    domain = f["email"].rsplit("@", 1)[1]
    conn = db.connect()
    home = district_for_domain(conn, domain)
    home = dict(home) if home else None
    join = None                                      # the existing school they confirmed, if any
    if home:
        choice = request.form.get("match", "")
        if choice.isdigit():
            join = conn.execute("SELECT id, name FROM schools WHERE id=? AND district_id=? AND "
                                "COALESCE(guest,0)=0", (int(choice), home["id"])).fetchone()
            join = dict(join) if join else None
        if not join and choice != "new":
            cands = [dict(c) for c in matching_schools(conn, home["id"], f["school"])]
            if cands:
                # Asked before the existing-account check on purpose: the page must look the
                # same whether or not this address already has a login.
                conn.close()
                if _throttled(_ip(), "lookup", _MAX_LOOKUPS):
                    return too_many
                return _confirm(f, home, cands)
    conn.close()

    if _throttled(_ip()):
        return too_many

    existing = find_user_by_email(f["email"])
    if existing:
        # No account enumeration: the page looks the same either way; the email says what is true.
        _email_existing(existing)
        return _sent(f["email"])

    from .road import _attr_from_cookie
    attr = _attr_from_cookie()

    if home:                                         # join the district that is already here
        did = home["id"]
        if join:
            sid, school, kind = join["id"], join["name"], "coach"
        else:
            conn = db.connect()
            sid = conn.execute("INSERT INTO schools (district_id, name) VALUES (?,?)",
                               (did, f["school"])).lastrowid
            conn.commit()
            conn.close()
            school, kind = f["school"], "school"
        _uid, token = create_user(f["email"], "coach", district_id=did, name=f["who"] or None, school_ids=[sid])
        log.info("self-serve sign-up joined district %s by email domain: %s %s", did, kind, sid)
        _send_welcome(f["email"], f["who"], school, token, joined=home["name"], kind=kind,
                      subscribed=billing.plan_of(home["settings_json"]) == billing.PLAN_SUB)
        try:
            _notify_operator(f, did, [], attr, joined=home, kind=kind, school=school)
        except Exception:
            log.exception("sign-up notification failed for district %s", did)
        return _sent(f["email"])

    dname = f["district"] or f["school"]
    conn = db.connect()
    similar = [r["name"] for r in conn.execute(
        "SELECT name FROM districts WHERE lower(name)=lower(?)", (dname,)).fetchall()]
    settings = {"plan": billing.PLAN_MEET,
                "self_serve": {"at": _iso(_now()), "by": f["email"], "state": f["state"],
                               "level": f["level"], "attribution": attr,
                               # short form: level, state and district come on the setup page
                               "details_pending": not f["who"]}}
    if domain not in PUBLIC_DOMAINS and parse_domains(domain) and not districts_claiming(conn, domain):
        settings["email_domains"] = [domain]         # the next coach at this domain joins this district
    if LEVELS[f["level"]][1]:
        settings["grades"] = LEVELS[f["level"]][1]
    did = conn.execute("INSERT INTO districts (name, slug, settings_json) VALUES (?,?,?)",
                       (dname, _slug(conn, dname), json.dumps(settings))).lastrowid
    sid = conn.execute("INSERT INTO schools (district_id, name) VALUES (?,?)", (did, f["school"])).lastrowid
    conn.commit()
    conn.close()
    _uid, token = create_user(f["email"], "coach", district_id=did, name=f["who"] or None, school_ids=[sid])
    log.info("self-serve school sign-up: district %s school %s", did, sid)
    _send_welcome(f["email"], f["who"], f["school"], token)
    try:
        _notify_operator(f, did, similar, attr)
    except Exception:                                 # the sign-up must not fail on the lead email
        log.exception("sign-up notification failed for district %s", did)
    return _sent(f["email"])


# ------------------------------- emails -------------------------------
def _send_welcome(email, who, school, token, joined=None, kind=None, subscribed=False):
    """joined = the name of the existing district they were added to (by email domain);
    kind = "coach" (an existing school) or "school" (a new school in that district)."""
    link = f"{_public_url()}/setup?token={token}"
    fee = billing.fee_str()
    if joined and kind == "coach":
        subject = f"You're a coach for {school} on XCTimer"
        intro = (f"<p>You have been added as a coach for <b>{escape(school)}</b>, which "
                 f"{escape(joined)} already has on XCTimer. Choose a password to get in:</p>")
        nxt = "<p>Your school's roster and meets are already there. "
    elif joined:
        subject = f"Finish setting up {school} on XCTimer"
        intro = (f"<p><b>{escape(school)}</b> has been added to <b>{escape(joined)}</b>, which already "
                 f"uses XCTimer. Choose a password to get in:</p>")
        nxt = "<p>Then import your roster and build your first meet. "
    else:
        subject = f"Finish setting up {school} on XCTimer"
        intro = f"<p><b>{escape(school)}</b> is ready on XCTimer. Choose a password to get in:</p>"
        nxt = "<p>Then import your roster and build your first meet. "
    money = ("</p>" if joined and subscribed else
             f"Setting everything up is free. It is {fee} when a meet goes live, and visiting teams never pay.</p>")
    send_email(email, subject,
               f"<p>Hi{(' ' + escape(who)) if who else ''},</p>{intro}"
               f'<p><a href="{link}">{link}</a></p>'
               f"{nxt}{money}"
               f"<p>The link works for 7 days. If you didn't ask for this, ignore this email.</p>"
               f"<p>Questions? Just reply, or write to rob@xctimer.com.</p>")


def _email_existing(u):
    """Someone signed up with an address that already has a login."""
    base = _public_url()
    if not u["password_hash"]:                       # invited or signed up before, never finished
        link = f"{base}/setup?token={issue_reset_token(u['id'])}"
        body = (f"<p>You already started an XCTimer account with this address. "
                f"Use this link to finish setting it up:</p><p><a href=\"{link}\">{link}</a></p>")
    else:
        body = (f"<p>Someone (hopefully you) tried to sign up for XCTimer with this address, which "
                f"already has an account.</p><p><a href=\"{base}/login\">Sign in here</a>, or use "
                f"“Forgot password” on that page.</p>")
    send_email(u["email"], "Your XCTimer account", body + "<p>If this wasn't you, ignore this email.</p>")


def _notify_operator(f, did, similar, attr, joined=None, kind=None, school=None):
    to = os.environ.get("XC_REG_NOTIFY", "rob@xctimer.com")
    if joined:
        return _notify_join(to, f, joined, kind, school, attr)
    later = "(asked after the email link)" if not f["who"] else None
    rows = [("School", f["school"]), ("District", later or f["district"] or "(none given)"),
            ("Level", later or LEVELS[f["level"]][0]), ("State", later or f["state"] or "-"),
            ("Contact", f"{f['who']} <{f['email']}>" if f["who"] else f["email"]),
            ("Came from", ", ".join(f"{k}={v}" for k, v in attr.items()) or "direct")]
    if similar:
        rows.append(("Heads up", "a district with this name already exists: " + ", ".join(similar)))
    trs = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in rows)
    send_email(to, f"New school sign-up: {f['school']}",
               f"<p>A school just signed itself up (district id {did}, tagged Pay per meet; "
               f"the contact has a coach login, no district admin).</p>"
               f"<table cellpadding=4>{trs}</table>"
               f'<p><a href="{_public_url()}/districts">Open Districts</a></p>')


def _notify_join(to, f, district, kind, school, attr):
    """A sign-up that joined an existing district because the email domain matched."""
    plan = billing.PLAN_LABEL[billing.plan_of(district["settings_json"])]
    domain = f["email"].rsplit("@", 1)[1]
    if kind == "coach":
        subject = f"Coach joined {school}: {f['who']}"
        what = (f"A coach signed up and confirmed an existing school, so they were added as a coach "
                f"of <b>{escape(school)}</b> and can see its roster and meets.")
        typed = [("They typed", f["school"])]
    else:
        subject = f"School joined {district['name']}: {school}"
        what = (f"A coach signed up and <b>{escape(school)}</b> was added as a new school in this "
                f"district. Check it is not a duplicate of a school already there"
                + (", and bill the school: this district is on the subscription." if plan == "Paid subscription" else "."))
        typed = []
    rows = [("District", f"{district['name']} (id {district['id']}, {plan})"),
            ("Matched on", f"email domain {domain}"), ("School", school)] + typed + [
            ("Contact", f"{f['who']} <{f['email']}>" if f["who"] else f["email"]),
            ("Came from", ", ".join(f"{k}={v}" for k, v in attr.items()) or "direct")]
    trs = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in rows)
    send_email(to, subject,
               f"<p>{what}</p><table cellpadding=4>{trs}</table>"
               f"<p>They get in only from the link emailed to that address. If this person should not "
               f"be there, remove them on the Users page.</p>"
               f'<p><a href="{_public_url()}/districts">Open Districts</a></p>')


# ------------------------------- details asked after the email link (1.126.0) -------------------------------
def _pending_district(conn, u):
    """The self-serve district this user created from the short form and has not described yet."""
    if not u["district_id"]:
        return None
    d = conn.execute("SELECT id, name, settings_json FROM districts WHERE id=?", (u["district_id"],)).fetchone()
    if not d:
        return None
    try:
        st = json.loads(d["settings_json"] or "{}")
    except (ValueError, TypeError):
        return None
    ss = st.get("self_serve")
    if not isinstance(ss, dict) or not ss.get("details_pending") or ss.get("by") != u["email"]:
        return None
    return {"id": d["id"], "name": d["name"], "settings": st}


def setup_extra(u, v=None):
    """Extra fields for the /setup password page: the user's name if we do not have it, and the
    school's level, state and district if they signed up with the short /start form."""
    v = v or {}
    out = ""
    if not (u["name"] or "").strip():
        out += (f'<label>Your name</label><input name="who" required maxlength="80" '
                f'value="{escape(v.get("who", ""))}" autocomplete="name">')
    conn = db.connect()
    d = _pending_district(conn, u)
    conn.close()
    if d:
        opts = "".join(f'<option value="{k}"{" selected" if v.get("level") == k else ""}>{lbl}</option>'
                       for k, (lbl, _g) in LEVELS.items())
        out += (f'<label>Level</label><select name="level">{opts}</select>'
                f'<label>State</label><input name="state" maxlength="30" value="{escape(v.get("state", ""))}" '
                f'placeholder="e.g. Utah">'
                f'<label>District <span class="muted">(optional)</span></label><input name="district" '
                f'maxlength="80" value="{escape(v.get("district", ""))}" placeholder="e.g. Maple Grove School District">')
    if out:
        out = ('<p class="muted" style="margin:.2rem 0 .4rem">A few details about you and your school, '
               'then choose a password.</p>' + out)
    return out


def save_setup_extra(u, form):
    """Store what setup_extra asked for. Returns an error message, or None when all is well."""
    who = _clean(form.get("who"))
    need_name = not (u["name"] or "").strip()
    if need_name and not who:
        return "Please enter your name."
    conn = db.connect()
    d = _pending_district(conn, u)
    if need_name:
        conn.execute("UPDATE users SET name=? WHERE id=?", (who, u["id"]))
    rows = []
    if d:
        level = form.get("level") if form.get("level") in LEVELS else "ms"
        state, dname = _clean(form.get("state"), 30), _clean(form.get("district"))
        st = d["settings"]
        st["self_serve"].update({"level": level, "state": state, "details_pending": False})
        if LEVELS[level][1]:
            st["grades"] = LEVELS[level][1]
        new_name = dname or d["name"]
        conn.execute("UPDATE districts SET name=?, settings_json=? WHERE id=?", (new_name, json.dumps(st), d["id"]))
        school = conn.execute("SELECT name FROM schools WHERE district_id=? ORDER BY id", (d["id"],)).fetchone()
        rows = [("School", school["name"] if school else "-"), ("District", dname or "(none given)"),
                ("Level", LEVELS[level][0]), ("State", state or "-")]
    conn.commit()
    conn.close()
    if rows or need_name:
        rows = [("Contact", f"{who or u['name']} <{u['email']}>")] + rows
        trs = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(val))}</td></tr>" for k, val in rows)
        try:
            send_email(os.environ.get("XC_REG_NOTIFY", "rob@xctimer.com"),
                       f"Sign-up details: {u['email']}",
                       f"<p>A coach who signed up with the short form opened their link and filled in "
                       f"the rest.</p><table cellpadding=4>{trs}</table>"
                       f'<p><a href="{_public_url()}/districts">Open Districts</a></p>')
        except Exception:                             # the password page must not fail on the email
            log.exception("sign-up details email failed for user %s", u["id"])
    return None


# ------------------------------- first-run help -------------------------------
def getting_started(p, did):
    """First-run card for a self-serve district until it has a roster and a meet. Shown on the
    coach's roster page (where a new sign-up lands) and on the admin dashboard."""
    if p.is_super or not did or getattr(p, "guest", False) or getattr(p, "meet_scope", None):
        return ""
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    if not d or not is_self_serve(d["settings_json"]):
        conn.close()
        return ""
    mine = sorted(p.school_ids()) if p.role == "coach" else []
    if mine:                                             # a coach: their own school's roster
        marks = ",".join("?" * len(mine))
        n_ath = conn.execute(f"SELECT COUNT(*) FROM athletes WHERE school_id IN ({marks})", mine).fetchone()[0]
        sid = {"id": mine[0]}
    else:
        n_ath = conn.execute("SELECT COUNT(*) FROM athletes a JOIN schools s ON s.id=a.school_id "
                             "WHERE s.district_id=?", (did,)).fetchone()[0]
        sid = conn.execute("SELECT id FROM schools WHERE district_id=? AND COALESCE(guest,0)=0 ORDER BY id",
                           (did,)).fetchone()
    n_meet = conn.execute("SELECT COUNT(*) FROM meets WHERE district_id=?", (did,)).fetchone()[0]
    conn.close()
    if n_ath and n_meet:
        return ""

    def step(done, text):
        mark = "✅" if done else "⬜"
        return f'<li style="margin:.35rem 0;list-style:none">{mark} {text}</li>'
    roster = f'/schools/{sid["id"]}' if sid else "/schools"
    if request.path.startswith("/schools/"):              # already on the roster page
        add = "<b>Add your roster</b> on this page"
    else:
        add = f'<a href="{roster}"><b>Add your roster</b></a>'
    return (f'<div class="card" style="border:2px solid #ea6a2d"><h2 style="margin-top:0">👋 Getting started</h2>'
            f'<ul style="padding:0;margin:0">'
            + step(bool(n_ath), f'{add}: import a spreadsheet, a photo of a list, or type names in.')
            + step(bool(n_meet), '<a href="/meets"><b>Create a meet</b></a>: pick the date, then add events, entries and heats.')
            + step(False, 'Invite visiting teams from the meet page. They enter their own athletes, free.')
            + step(False, f'Go live for {billing.fee_str()} (or a promo code) when you are ready to time it.')
            + '</ul></div>')
