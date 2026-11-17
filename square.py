"""Square one-time hosted checkout for the go-live fee ($100 per event or school meet).

Mirrors 321draw's Square boundary (app/square_billing.py) but: (a) stdlib urllib —
no httpx dependency; (b) a ONE-TIME quick_pay payment link, not a subscription. After
the buyer pays on Square's hosted page, Square redirects back with ?orderId=… and we
verify the order is paid in full (and tagged for this meet) before publishing the event —
so payment is actually verified, not honor-system. See paid_order() for what "paid" means:
a payment-link order stays OPEN after it is paid, so the payments are what get checked.

Env (loaded by systemd from ~/xctimer/env):
  SQUARE_ENVIRONMENT   'production' | 'sandbox' (default sandbox)
  SQUARE_ACCESS_TOKEN  account access token (shared with the other Rohde Square apps)
  SQUARE_LOCATION_ID   the XCTimer location (LGXPPYDV1GASR)
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid

log = logging.getLogger("xctimer.square")


def _env(k, d=""):
    return os.environ.get(k, d)


def is_configured():
    return bool(_env("SQUARE_ACCESS_TOKEN") and _env("SQUARE_LOCATION_ID"))


def _base_url():
    return ("https://connect.squareup.com"
            if _env("SQUARE_ENVIRONMENT", "sandbox").lower() == "production"
            else "https://connect.squareupsandbox.com")


def _request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(_base_url() + path, data=data, method=method, headers={
        "Authorization": f"Bearer {_env('SQUARE_ACCESS_TOKEN')}",
        "Square-Version": "2024-09-19",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        log.error("Square %s %s -> HTTP %s %s", method, path, e.code, e.read().decode()[:500])
        raise


def create_payment_link(name, amount_cents, redirect_url, note):
    """One-time hosted checkout. Returns the Square URL to redirect the buyer to."""
    payload = {
        "idempotency_key": str(uuid.uuid4()),
        "quick_pay": {
            "name": name[:255],
            "price_money": {"amount": int(amount_cents), "currency": "USD"},
            "location_id": _env("SQUARE_LOCATION_ID"),
        },
        "checkout_options": {"redirect_url": redirect_url, "ask_for_shipping_address": False},
        "payment_note": note,          # lands on the PAYMENT's note (not the order's): bind + verify
        "description": name[:255],
    }
    data = _request("POST", "/v2/online-checkout/payment-links", payload)
    return data["payment_link"]["url"]


def paid_order(order_id):
    """{"note": str, "amount": cents} for an order that has been paid in full, else None
    (unknown, unpaid, part-paid, refunded, or any error).

    A payment-link (quick_pay) order does NOT turn COMPLETED when the buyer pays: it stays
    OPEN, with its digital fulfillment still PROPOSED, and the link's `payment_note` lands on
    the PAYMENT's note, not on the order's. So "paid" is read from the order's payments: the
    COMPLETED ones, less refunds, must cover the order total. `note` is the order's note and
    its payments' notes together, which is where the meet tag is found. `amount` is what was
    actually collected."""
    if not order_id:
        return None
    try:
        o = _request("GET", f"/v2/orders/{order_id}").get("order", {})
        if o.get("state") not in ("OPEN", "COMPLETED"):
            return None
        loc = _env("SQUARE_LOCATION_ID")
        if loc and o.get("location_id") and o["location_id"] != loc:
            return None                        # the token is shared with other Square apps
        total = int((o.get("total_money") or {}).get("amount") or 0)
        notes, got = [o.get("note") or ""], 0
        for t in o.get("tenders") or []:
            pid = t.get("payment_id") or t.get("id")
            if not pid:
                continue
            pay = _request("GET", f"/v2/payments/{pid}").get("payment", {})
            if pay.get("status") != "COMPLETED" or pay.get("order_id") != order_id:
                continue
            got += (int((pay.get("total_money") or {}).get("amount") or 0)
                    - int((pay.get("refunded_money") or {}).get("amount") or 0))
            notes.append(pay.get("note") or "")
        if total <= 0 or got < total:
            return None
        return {"note": " ".join(n for n in notes if n), "amount": got}
    except Exception:
        log.exception("paid_order failed for %s", order_id)
        return None


RETURN_TRIES = 4                # how many looks the return page takes at a fresh payment
RETURN_WAIT = 1.5               # seconds between them


def until_paid(check):
    """Square sends the buyer back a second or two before the card payment turns COMPLETED,
    so the return page takes a few looks before telling someone who has just paid that it
    did not work. `check` is a no-argument callable; returns its first truthy result, else
    its last one. (The webhook covers a payment that settles later still.)"""
    res = None
    for i in range(RETURN_TRIES):
        res = check()
        if res:
            break
        if i < RETURN_TRIES - 1:
            time.sleep(RETURN_WAIT)
    return res


def order_ok(order_id, expect_note_substr=None):
    """True iff the order is paid in full and (optionally) its note carries
    `expect_note_substr` -- so a replayed / cross-event orderId can't publish the wrong
    event. Any error -> False (never publish on an unverifiable order)."""
    o = paid_order(order_id)
    if not o:
        return False
    # Exact id match: "xctimer_meet=2" must not accept an order made for meet 26.
    return not expect_note_substr or bool(
        re.search(re.escape(expect_note_substr) + r"(?!\d)", o["note"]))


def completed_order(order_id):
    """{"note": str, "amount": cents} for a paid order, else None. The caller decides what
    the note and amount must be."""
    return paid_order(order_id)


def order_meet_id(order_id):
    """Parse `xctimer_meet=<id>` from a paid order's note (set at checkout). Used by the
    webhook to bind a payment to its event. Returns int or None."""
    o = paid_order(order_id)
    mt = re.search(r"xctimer_meet=(\d+)", o["note"]) if o else None
    return int(mt.group(1)) if mt else None


def verify_webhook_signature(body_bytes, signature_header, notification_url):
    """Validate Square's X-Square-Hmacsha256-Signature: base64(HMAC-SHA256(key,
    notification_url + body)). `notification_url` must exactly match the URL
    registered on the webhook subscription. False when the key/header is missing
    or doesn't match (caller rejects with 401)."""
    key = _env("SQUARE_WEBHOOK_SIGNATURE_KEY")
    if not key or not signature_header:
        return False
    payload = notification_url.encode("utf-8") + body_bytes
    expected = base64.b64encode(
        hmac.new(key.encode("utf-8"), payload, hashlib.sha256).digest()).decode("ascii")
    return hmac.compare_digest(expected, signature_header.strip())
