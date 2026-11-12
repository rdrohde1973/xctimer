"""Self-serve sign-up for schools (1.113.0): xctimer.com/start.

A coach fills in one short form and gets, with nobody at XCTimer involved:

  * a district of their own, tagged Pay per meet (billing.py), holding
  * their school, and
  * a district-admin login for themselves, linked to that school, set up from an emailed link
    (which is also what proves the address is theirs).

Nothing here costs XCTimer anything: the meet they build cannot be timed until the $100
meet fee is paid or a promo code is entered. Every sign-up emails the operator, so each one
is a lead -- including the ones that belong in a district subscription instead.

A sign-up never joins an existing district, even when the name matches: that would show
another school's roster to whoever typed the name. The operator email points out a likely
match so the two can be merged by hand.
"""
import json
import logging
import os
import re
import time
from html import escape

from flask import Blueprint, g, make_response, redirect, request

from . import db, billing
from .auth import create_user, find_user_by_email, issue_reset_token, send_email, _public_url, _iso, _now
from .ui import HEAD_EXTRA, CSRF_JS

bp = Blueprint("signup", __name__)
log = logging.getLogger("xctimer.signup")

LEVELS = {                      # form value -> (label, district grade list or None for the default 6-9)
    "ms": ("Middle school / junior high", None),
    "hs": ("High school", [9, 10, 11, 12]),
    "both": ("Both (grades 6-12)", [6, 7, 8, 9, 10, 11, 12]),
}
_HITS = {}                      # ip -> [timestamps]; a small in-memory brake on scripted sign-ups
_MAX_PER_HOUR = 5


def _throttled(ip):
    now = time.time()
    hits = [t for t in _HITS.get(ip, []) if now - t < 3600]
    if len(hits) >= _MAX_PER_HOUR:
        _HITS[ip] = hits
        return True
    hits.append(now)
    _HITS[ip] = hits
    return False


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
def _page(title, inner):
    return (f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>{escape(title)} · XCTimer</title>{HEAD_EXTRA}<script>{CSRF_JS}</script>
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


def _form(err="", v=None):
    v = v or {}
    val = lambda k: escape(v.get(k, ""))                                   # noqa: E731
    opts = "".join(f'<option value="{k}"{" selected" if v.get("level") == k else ""}>{lbl}</option>'
                   for k, (lbl, _g) in LEVELS.items())
    fee = billing.fee_str()
    errp = f'<p class="err">{escape(err)}</p>' if err else ""
    return _page("Set up your school", f"""<h1>Set up your school on XCTimer.</h1>
<p>Rosters, bibs, heats, phone timing and live results for your cross country and track meets.
Build everything free. It is {fee} only when a meet goes live.</p>
<div class="card" id="create">{errp}<form method="post" action="/start">
<label>School name</label><input name="school" required maxlength="80" value="{val('school')}" placeholder="e.g. Maple Grove Middle School">
<label>District <span class="opt">(optional)</span></label><input name="district" maxlength="80" value="{val('district')}" placeholder="e.g. Maple Grove School District">
<div style="display:flex;gap:.7rem;flex-wrap:wrap">
<div style="flex:2;min-width:12rem"><label>Level</label><select name="level">{opts}</select></div>
<div style="flex:1;min-width:6rem"><label>State</label><input name="state" maxlength="30" value="{val('state')}" placeholder="e.g. Utah"></div></div>
<label>Your name</label><input name="who" required maxlength="80" value="{val('who')}">
<label>Your email</label><input name="email" type="email" required maxlength="120" value="{val('email')}">
<div class="hp" aria-hidden="true"><label>Website</label><input name="website" tabindex="-1" autocomplete="off"></div>
<p class="fine">We email you a private link to finish setting up. Use your school email if you have one.</p>
<button class="btn" type="submit">Create my school →</button>
<p class="fine" style="margin:.7rem 0 0">By signing up you confirm your school lets you manage its team roster.
See <a href="/security">Security &amp; data privacy</a>.</p>
</form></div>
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
Already have an account? <a href="/login">Sign in</a>.</p>""")


def _sent(email):
    return _page("Check your email",
                 f'<div class="card"><h1>✅ Check your email</h1><p>We emailed <b>{escape(email)}</b> a private '
                 f'link to finish setting up. It comes from <b>XCTimer</b> and works for 7 days.</p>'
                 f'<p>Check your spam folder if it doesn’t arrive in a few minutes. Wrong address? '
                 f'<a href="/start">Go back</a>.</p></div>')


@bp.get("/start")
def start():
    if getattr(g, "principal", None) and not getattr(g.principal, "meet_scope", None):
        from .ui import home_url
        return redirect(home_url(g.principal))
    from .road import capture_attribution
    return capture_attribution(make_response(_form()))


@bp.post("/start")
def create():
    f = {k: _clean(request.form.get(k)) for k in ("school", "district", "state", "who")}
    f["email"] = _clean(request.form.get("email"), 120).lower()
    f["level"] = request.form.get("level") if request.form.get("level") in LEVELS else "ms"
    if request.form.get("website"):                  # honeypot: a person never sees this field
        return _sent(f["email"] or "you")
    if not f["school"] or not f["who"] or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
        return _form("Please enter your school, your name and a valid email.", f), 400
    if _throttled(_ip()):
        return _form("Too many sign-ups from this network. Please try again in an hour, "
                     "or email rob@xctimer.com.", f), 429

    existing = find_user_by_email(f["email"])
    if existing:
        # No account enumeration: the page looks the same either way; the email says what is true.
        _email_existing(existing)
        return _sent(f["email"])

    from .road import _attr_from_cookie
    attr = _attr_from_cookie()
    dname = f["district"] or f["school"]
    conn = db.connect()
    similar = [r["name"] for r in conn.execute(
        "SELECT name FROM districts WHERE lower(name)=lower(?)", (dname,)).fetchall()]
    settings = {"plan": billing.PLAN_MEET,
                "self_serve": {"at": _iso(_now()), "by": f["email"], "state": f["state"],
                               "level": f["level"], "attribution": attr}}
    if LEVELS[f["level"]][1]:
        settings["grades"] = LEVELS[f["level"]][1]
    did = conn.execute("INSERT INTO districts (name, slug, settings_json) VALUES (?,?,?)",
                       (dname, _slug(conn, dname), json.dumps(settings))).lastrowid
    sid = conn.execute("INSERT INTO schools (district_id, name) VALUES (?,?)", (did, f["school"])).lastrowid
    conn.commit()
    conn.close()
    _uid, token = create_user(f["email"], "district_admin", district_id=did, name=f["who"], school_ids=[sid])
    log.info("self-serve school sign-up: district %s school %s", did, sid)
    _send_welcome(f["email"], f["who"], f["school"], token)
    try:
        _notify_operator(f, did, similar, attr)
    except Exception:                                 # the sign-up must not fail on the lead email
        log.exception("sign-up notification failed for district %s", did)
    return _sent(f["email"])


# ------------------------------- emails -------------------------------
def _send_welcome(email, who, school, token):
    link = f"{_public_url()}/setup?token={token}"
    fee = billing.fee_str()
    send_email(email, f"Finish setting up {school} on XCTimer",
               f"<p>Hi {escape(who)},</p>"
               f"<p><b>{escape(school)}</b> is ready on XCTimer. Choose a password to get in:</p>"
               f'<p><a href="{link}">{link}</a></p>'
               f"<p>Then import your roster and build your first meet. Setting everything up is free. "
               f"It is {fee} when a meet goes live, and visiting teams never pay.</p>"
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


def _notify_operator(f, did, similar, attr):
    to = os.environ.get("XC_REG_NOTIFY", "rob@xctimer.com")
    rows = [("School", f["school"]), ("District", f["district"] or "(none given)"),
            ("Level", LEVELS[f["level"]][0]), ("State", f["state"] or "-"),
            ("Contact", f"{f['who']} <{f['email']}>"),
            ("Came from", ", ".join(f"{k}={v}" for k, v in attr.items()) or "direct")]
    if similar:
        rows.append(("Heads up", "a district with this name already exists: " + ", ".join(similar)))
    trs = "".join(f"<tr><td><b>{escape(k)}</b></td><td>{escape(str(v))}</td></tr>" for k, v in rows)
    send_email(to, f"New school sign-up: {f['school']}",
               f"<p>A school just signed itself up (district id {did}, tagged Pay per meet).</p>"
               f"<table cellpadding=4>{trs}</table>"
               f'<p><a href="{_public_url()}/districts">Open Districts</a></p>')


# ------------------------------- first-run help -------------------------------
def getting_started(p, did):
    """Dashboard card for a self-serve district until it has a roster and a meet."""
    if p.is_super or not did:
        return ""
    conn = db.connect()
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    if not d or not is_self_serve(d["settings_json"]):
        conn.close()
        return ""
    n_ath = conn.execute("SELECT COUNT(*) FROM athletes a JOIN schools s ON s.id=a.school_id "
                         "WHERE s.district_id=?", (did,)).fetchone()[0]
    n_meet = conn.execute("SELECT COUNT(*) FROM meets WHERE district_id=?", (did,)).fetchone()[0]
    sid = conn.execute("SELECT id FROM schools WHERE district_id=? AND COALESCE(guest,0)=0 ORDER BY id",
                       (did,)).fetchone()
    conn.close()
    if n_ath and n_meet:
        return ""

    def step(done, text):
        mark = "✅" if done else "⬜"
        return f'<li style="margin:.35rem 0;list-style:none">{mark} {text}</li>'
    roster = f'/schools/{sid["id"]}' if sid else "/schools"
    return (f'<div class="card" style="border:2px solid #ea6a2d"><h2 style="margin-top:0">👋 Getting started</h2>'
            f'<ul style="padding:0;margin:0">'
            + step(bool(n_ath), f'<a href="{roster}"><b>Add your roster</b></a>: import a spreadsheet, a photo of a list, or type names in.')
            + step(bool(n_meet), '<a href="/meets"><b>Create a meet</b></a>: pick the date, then add events, entries and heats.')
            + step(False, 'Invite visiting teams from the meet page. They enter their own athletes, free.')
            + step(False, f'Go live for {billing.fee_str()} (or a promo code) when you are ready to time it.')
            + '</ul></div>')
