"""District billing plan and the pay-per-meet "go live" gate for school meets (1.112.0).

Every district carries a plan, set by the Super Admin on the Districts page:

  subscription  the district pays for the season; every meet is live as soon as it is made.
  per_meet      anyone who may create a meet can build it for free (schools, events, entries,
                heats, printing), but timing, the Phone Timer App link and results recording
                stay locked until the meet fee is paid by card through Square, or the Super
                Admin marks the meet as covered.

A district with no plan stored counts as `subscription`, so nothing changes for a district
until the Super Admin tags it. Practice time trials and community road events are never
gated here (fun-run events have their own go-live flow in road.py, at the same price).

A promo code (the same promo_codes the fun-run flow uses) takes the fee off: 100% goes live
with no payment, a partial % sends the host to Square for the reduced amount.

Per-meet state lives in meets.settings_json["meet_fee"]:
  {"paid": true, "how": "square" | "promo" | "comp" | "included", "order_id": ..., "code": ...,
   "at": iso, "by": email}
and, while a partial-discount checkout is open, settings_json["meet_fee_promo"] = {"code", "pct"}.
"""
import json
import logging
import os
import re
from datetime import datetime, timezone
from html import escape

from flask import Blueprint, abort, g, jsonify, redirect, request

from . import db
from .auth import login_required, role_required

bp = Blueprint("billing", __name__)
log = logging.getLogger("xctimer.billing")

PLAN_SUB = "subscription"
PLAN_MEET = "per_meet"
PLAN_LABEL = {PLAN_SUB: "Paid subscription", PLAN_MEET: "Pay per meet"}
MEET_FEE_CENTS = int(os.environ.get("XC_MEET_FEE_CENTS", "10000"))     # $100 per hosted meet
NOTE_TAG = "xctimer_schoolmeet"       # deliberately not road.py's "xctimer_meet" tag
LOCKED_MSG = ("This meet isn't live yet. The host turns on timing and results by paying "
              "the meet fee on the meet's Setup page.")


def fee_str(cents=None):
    cents = MEET_FEE_CENTS if cents is None else cents
    return f"${cents // 100}" if cents % 100 == 0 else f"${cents / 100:.2f}"


def _json(s):
    try:
        return json.loads(s or "{}") or {}
    except (ValueError, TypeError):
        return {}


def _now():
    return datetime.now(timezone.utc).isoformat()


# ------------------------------- district plan -------------------------------
def plan_of(settings_json):
    p = _json(settings_json).get("plan")
    return p if p in PLAN_LABEL else PLAN_SUB


def district_plan(did, conn=None):
    if did is None:
        return PLAN_SUB
    own = conn is None
    conn = conn or db.connect()
    try:
        d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    finally:
        if own:
            conn.close()
    return plan_of(d["settings_json"] if d else None)


def set_district_plan(conn, did, plan, by=None):
    """Store the plan. Moving a district ONTO pay-per-meet marks the meets it already has as
    included, so a meet that is under way (or finished, with public results) never goes dark;
    only meets created afterwards need the fee. Caller commits."""
    if plan not in PLAN_LABEL:
        raise ValueError(plan)
    d = conn.execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()
    if not d:
        return False
    s = _json(d["settings_json"])
    was = plan_of(d["settings_json"])
    s["plan"] = plan
    conn.execute("UPDATE districts SET settings_json=? WHERE id=?", (json.dumps(s), did))
    if plan == PLAN_MEET and was != PLAN_MEET:
        for m in conn.execute("SELECT id, settings_json FROM meets WHERE district_id=? "
                              "AND organizer_id IS NULL", (did,)).fetchall():
            ms = _json(m["settings_json"])
            if not (ms.get("meet_fee") or {}).get("paid"):
                ms["meet_fee"] = {"paid": True, "how": "included", "at": _now(), "by": by}
                conn.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps(ms), m["id"]))
    return True


# ------------------------------- per-meet state -------------------------------
def fee_state(m):
    return _json(m["settings_json"]).get("meet_fee") or {}


def needs_fee(m, conn=None):
    """True when this meet is the kind that is charged per meet: a school meet (not a road
    event, not a practice time trial) in a pay-per-meet district."""
    keys = m.keys()
    if "organizer_id" in keys and m["organizer_id"] is not None:
        return False
    if m["district_id"] is None:
        return False
    if "time_trial" in keys and m["time_trial"]:
        return False
    return district_plan(m["district_id"], conn) == PLAN_MEET


def meet_live(m, conn=None):
    return (not needs_fee(m, conn)) or bool(fee_state(m).get("paid"))


def _set_fee(mid, state):
    conn = db.connect()
    row = conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()
    if not row:
        conn.close()
        return False
    s = _json(row["settings_json"])
    if state is None:
        s.pop("meet_fee", None)
    else:
        s["meet_fee"] = state
    conn.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps(s), mid))
    conn.commit()
    conn.close()
    return True


def mark_paid(mid, order_id, by=None):
    """Idempotent: the Square return page and the webhook may both land."""
    conn = db.connect()
    row = conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not row:
        return False
    if (_json(row["settings_json"]).get("meet_fee") or {}).get("how") == "square":
        return True
    log.info("meet %s paid via Square order %s", mid, order_id)
    return _set_fee(mid, {"paid": True, "how": "square", "order_id": order_id,
                          "at": _now(), "by": by})


def meet_id_from_note(note):
    mt = re.search(rf"{NOTE_TAG}=(\d+)(?!\d)", note or "")
    return int(mt.group(1)) if mt else None


def discounted_cents(pct):
    return max(50, round(MEET_FEE_CENTS * (100 - pct) / 100))      # Square's minimum is about $0.50


def amount_due(mid):
    """What a Square order must cover for this meet: the fee, less a partial promo code the
    host has already applied."""
    conn = db.connect()
    row = conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    try:
        pct = int((_json(row["settings_json"] if row else None).get("meet_fee_promo") or {}).get("pct") or 0)
    except (ValueError, TypeError):
        pct = 0
    return discounted_cents(pct) if 0 < pct < 100 else MEET_FEE_CENTS


def order_pays_meet(order, mid):
    """`order` is square.completed_order(): {"note", "amount"} or None. True only when the
    order was created for THIS meet and covers what is due."""
    return bool(order) and meet_id_from_note(order.get("note")) == mid \
        and int(order.get("amount") or 0) >= amount_due(mid)


# ------------------------------- promo codes -------------------------------
def _promo_key(m):
    """Who a "first event only" code is counted against for a school meet: the host school
    (the district when the meet has no host). Stored in promo_redemptions.email, which the
    fun-run flow keys by host email, so the two never collide."""
    return f"school:{m['host_school_id']}" if m["host_school_id"] else f"district:{m['district_id']}"


def _first_meet_violation(code, m):
    """True when `code` is a first-event-only code and this host school has already used it
    on another meet. Read-only; runs before the code is consumed."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT first_event_only FROM promo_codes WHERE code=? AND active=1",
                           (code,)).fetchone()
        if not row or not row["first_event_only"]:
            return False
        return bool(conn.execute(
            "SELECT 1 FROM promo_redemptions WHERE email=? AND code=? "
            "AND (meet_token IS NULL OR meet_token<>?) LIMIT 1",
            (_promo_key(m), code, m["public_token"] or "")).fetchone())
    finally:
        conn.close()


# ------------------------------- routes -------------------------------
@bp.post("/districts/<int:did>/plan")
@role_required("super_admin")
def set_plan(did):
    plan = request.form.get("plan")
    if plan not in PLAN_LABEL:
        abort(400)
    conn = db.connect()
    ok = set_district_plan(conn, did, plan, by=g.principal.email)
    conn.commit()
    conn.close()
    if not ok:
        abort(404)
    return redirect("/districts")


def _meet_for_setup(mid):
    from .meets import load_meet, can_setup_meet
    m = load_meet(mid)
    if not can_setup_meet(m):
        abort(403)
    return m


@bp.post("/meets/<int:mid>/meet-fee/pay")
@login_required
def pay(mid):
    """Start a Square hosted checkout for the meet fee. JSON, so the button can navigate with
    location.href (a form POST that redirects to square.link is blocked by our CSP)."""
    m = _meet_for_setup(mid)
    if meet_live(m):
        return jsonify(paid=True)
    from . import square
    if not square.is_configured():
        return jsonify(error="Card payments aren’t set up yet. Contact XCTimer."), 400
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    try:
        url = square.create_payment_link(f"XCTimer meet: {m['name']}", amount_due(mid),
                                         f"{base}/meets/{mid}/meet-fee/return",
                                         f"{NOTE_TAG}={mid}")
    except Exception:
        log.exception("meet fee checkout failed for meet %s", mid)
        return jsonify(error="Couldn’t start Square checkout. Please try again."), 502
    return jsonify(url=url)


@bp.get("/meets/<int:mid>/meet-fee/return")
@login_required
def pay_return(mid):
    _meet_for_setup(mid)
    from . import square
    order_id = request.args.get("orderId") or ""
    if order_pays_meet(square.completed_order(order_id), mid):
        mark_paid(mid, order_id, by=g.principal.email)
        return redirect(f"/meets/{mid}?msg=Payment+received.+This+meet+is+live.")
    return redirect(f"/meets/{mid}?err=Payment+didn%27t+complete.+Nothing+was+charged+"
                    f"unless+Square+emailed+a+receipt.+Please+try+again.")


@bp.post("/meets/<int:mid>/meet-fee/redeem")
@login_required
def redeem(mid):
    """Apply a promo code to the meet fee. 100% off goes live at once; a partial % returns a
    Square checkout for the reduced amount. JSON, like pay()."""
    m = _meet_for_setup(mid)
    if meet_live(m):
        return jsonify(paid=True)
    code = ((request.get_json(silent=True) or {}).get("code") or request.form.get("code") or "").strip().upper()
    if not code:
        return jsonify(error="Enter a promo code."), 400
    if _first_meet_violation(code, m):          # before consuming, so a refusal doesn't burn a use
        return jsonify(error="That code is for a school's first meet only."), 400
    from .road import _consume_promo
    pct = _consume_promo(code)
    if pct is None:
        return jsonify(error="That promo code isn’t valid (or it’s been used up)."), 400
    conn = db.connect()
    conn.execute("INSERT INTO promo_redemptions (email, code, meet_token, created_at) VALUES (?,?,?,?)",
                 (_promo_key(m), code, m["public_token"], _now()))
    conn.commit()
    conn.close()
    if pct >= 100:
        _set_fee(mid, {"paid": True, "how": "promo", "code": code, "at": _now(), "by": g.principal.email})
        return jsonify(paid=True)
    from . import square
    if not square.is_configured():
        return jsonify(error="Card payments aren’t set up, so a partial discount can’t be applied."), 400
    conn = db.connect()
    s = _json(conn.execute("SELECT settings_json FROM meets WHERE id=?", (mid,)).fetchone()["settings_json"])
    s["meet_fee_promo"] = {"code": code, "pct": pct}
    conn.execute("UPDATE meets SET settings_json=? WHERE id=?", (json.dumps(s), mid))
    conn.commit()
    conn.close()
    base = os.environ.get("XC_PUBLIC_URL", request.host_url.rstrip("/"))
    try:
        url = square.create_payment_link(f"XCTimer meet: {m['name']} ({pct}% off)", discounted_cents(pct),
                                         f"{base}/meets/{mid}/meet-fee/return", f"{NOTE_TAG}={mid}")
    except Exception:
        log.exception("discounted meet fee checkout failed for meet %s", mid)
        return jsonify(error="Couldn’t start the discounted checkout. Please try again."), 502
    return jsonify(url=url)


@bp.post("/meets/<int:mid>/meet-fee/comp")
@role_required("super_admin")
def comp(mid):
    """Super Admin: mark a meet as covered without a card payment, or put the fee back."""
    from .meets import load_meet
    m = load_meet(mid)
    if "organizer_id" in m.keys() and m["organizer_id"] is not None:
        abort(400)
    if request.form.get("on") == "1":
        _set_fee(mid, {"paid": True, "how": "comp", "at": _now(), "by": g.principal.email})
    else:
        _set_fee(mid, None)
    return redirect(f"/meets/{mid}")


def handle_webhook_order(order_id):
    """Called from the Square webhook (road.square_webhook) for a COMPLETED payment, so a
    meet goes live even if the payer never comes back from Square's page."""
    from . import square
    order = square.completed_order(order_id)
    mid = meet_id_from_note((order or {}).get("note"))
    if mid and order_pays_meet(order, mid):
        mark_paid(mid, order_id)
        return True
    return False


# ------------------------------- UI -------------------------------
def plan_cell(d):
    """Districts page: the plan tag with a one-click change."""
    plan = plan_of(d["settings_json"])
    opts = "".join(f'<option value="{k}"{" selected" if k == plan else ""}>{v}</option>'
                   for k, v in PLAN_LABEL.items())
    color = "#2e8b57" if plan == PLAN_SUB else "#c9661b"
    return (f'<span style="display:inline-block;background:{color};color:#fff;border-radius:6px;'
            f'padding:.08rem .45rem;font-size:.74rem;font-weight:700;white-space:nowrap">'
            f'{PLAN_LABEL[plan]}</span>'
            f'<form class="inline" method="post" action="/districts/{d["id"]}/plan" '
            f'style="display:block;margin-top:.25rem"><select name="plan" '
            f'style="width:auto;font-size:.78rem;padding:.2rem">{opts}</select> '
            f'<button class="ghost" type="submit">Set</button></form>')


def create_note(did):
    """One line under the Create-a-meet form in a pay-per-meet district."""
    if district_plan(did) != PLAN_MEET:
        return ""
    return (f'<p class="muted" style="margin:.8rem 0 0">Setting up a meet is free. Going live '
            f'(timing, the Phone Timer App and results) is {fee_str()} per meet, paid by card '
            f'from the meet page when you are ready, or with a promo code. Practice time trials '
            f'are free.</p>')


def list_badge(m):
    """Meets list: a small tag on a meet that still needs the fee."""
    if meet_live(m):
        return ""
    return (' <span style="background:#fdf0e3;color:#9a4a0b;border-radius:6px;padding:.05rem .4rem;'
            'font-size:.72rem;font-weight:700;white-space:nowrap">Not live yet</span>')


def _super_tools(m, st):
    mid = m["id"]
    if st.get("paid"):
        how = {"square": "paid by card", "comp": "marked as covered",
               "promo": f'covered by promo code {escape(st.get("code") or "")}',
               "included": "included (existed before pay per meet)"}.get(st.get("how"), "live")
        who = f' by {escape(st["by"])}' if st.get("by") else ""
        return (f'<div class="muted" style="font-size:.85rem;margin:.2rem 0 .6rem">Super Admin: '
                f'meet fee {how}{who}. '
                f'<form class="inline" method="post" action="/meets/{mid}/meet-fee/comp" '
                f'onsubmit="return confirm(\'Require the meet fee again? Timing locks until it is paid.\')">'
                f'<input type="hidden" name="on" value="0">'
                f'<button class="ghost" type="submit" style="padding:.1rem .5rem">Require payment</button>'
                f'</form></div>')
    return (f'<form class="inline" method="post" action="/meets/{mid}/meet-fee/comp">'
            f'<input type="hidden" name="on" value="1">'
            f'<button class="ghost" type="submit">Super Admin: mark as covered (no charge)</button></form>')


def banner(mid):
    """Shown at the top of every school-meet page (it rides in the tab bar). Empty for a live
    meet, except a one-line status for the Super Admin."""
    from .meets import load_meet, can_setup_meet
    p = getattr(g, "principal", None)
    if not p:
        return ""
    conn = db.connect()
    m = conn.execute("SELECT * FROM meets WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not m or not needs_fee(m):
        return ""
    st = fee_state(m)
    if st.get("paid"):
        return _super_tools(m, st) if p.is_super else ""
    fee = fee_str()
    if not can_setup_meet(m) or getattr(p, "is_demo", False):
        who = "A demo account can’t pay." if getattr(p, "is_demo", False) else \
              "The host school turns it on from this page."
        return (f'<div class="card" style="border:2px solid #ea6a2d"><b>🚦 This meet isn’t live '
                f'yet.</b> <span class="muted">Timing, the Phone Timer App and results open once '
                f'the {fee} meet fee is paid. {who}</span></div>')
    from . import square
    if square.is_configured():
        pay_btn = (
            f'<button type="button" id="meetfeepay" onclick="payMeetFee()" '
            f'style="background:#006aff;color:#fff;border:0;border-radius:9px;padding:.55rem 1rem;'
            f'font-weight:700;cursor:pointer">💳 Pay {fee} with Square (card)</button>'
            f'<script>async function payMeetFee(){{var b=document.getElementById("meetfeepay"),'
            f't=b.textContent;b.disabled=true;b.textContent="Starting checkout…";'
            f'try{{var j=await jpost("/meets/{mid}/meet-fee/pay",{{}});'
            f'if(j&&j.url){{location.href=j.url;return;}}'
            f'if(j&&j.paid){{location.reload();return;}}throw new Error("Please try again.");}}'
            f'catch(e){{b.disabled=false;b.textContent=t;'
            f'alert(e.message||"Checkout failed. Please try again.");}}}}</script>')
    else:
        pay_btn = '<span class="muted">Card payments aren’t set up yet. Contact XCTimer.</span>'
    promo = (
        f'<span style="display:inline-flex;gap:.35rem;align-items:center">'
        f'<input id="meetfeecode" placeholder="Promo code" autocomplete="off" aria-label="Promo code" '
        f'style="max-width:130px;padding:.5rem" '
        f'onkeydown="if(event.key===\'Enter\'){{event.preventDefault();applyMeetCode();}}">'
        f'<button type="button" class="ghost" id="meetfeecodebtn" onclick="applyMeetCode()">Apply</button></span>'
        f'<script>async function applyMeetCode(){{var i=document.getElementById("meetfeecode"),'
        f'b=document.getElementById("meetfeecodebtn");var code=(i.value||"").trim();if(!code)return;'
        f'b.disabled=true;try{{var j=await jpost("/meets/{mid}/meet-fee/redeem",{{code:code}});'
        f'if(j&&j.paid){{location.href="/meets/{mid}?msg="+encodeURIComponent("Code applied. This meet is live.");return;}}'
        f'if(j&&j.url){{location.href=j.url;return;}}throw new Error("Please try again.");}}'
        f'catch(e){{b.disabled=false;alert(e.message||"That promo code isn\u2019t valid.");}}}}</script>')
    due = amount_due(mid)
    if due != MEET_FEE_CENTS and square.is_configured():
        pay_btn = pay_btn.replace(f"Pay {fee} with", f"Pay {fee_str(due)} with")
    sup = _super_tools(m, st) if p.is_super else ""
    return (f'<div class="card" style="border:2px solid #ea6a2d">'
            f'<h2 style="margin-top:0">🚦 Go live: {fee} for this meet</h2>'
            f'<p style="margin:.2rem 0 .6rem">Build the whole meet first: schools, events, entries, '
            f'heats and printing all work now. Paying turns on Race day timing, the Phone Timer App '
            f'and results. One payment covers every team in the meet. Have a promo code? Enter it '
            f'to go live free or take a discount off the fee.</p>'
            f'<div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:center">{pay_btn}{promo}{sup}</div>'
            f'</div>')
