"""Square one-time hosted checkout for the self-serve event fee ($50).

Mirrors 321draw's Square boundary (app/square_billing.py) but: (a) stdlib urllib —
no httpx dependency; (b) a ONE-TIME quick_pay payment link, not a subscription. After
the buyer pays on Square's hosted page, Square redirects back with ?orderId=… and we
verify the order is COMPLETED (and tagged for this meet) before publishing the event —
so payment is actually verified, not honor-system.

Env (loaded by systemd from ~/xctimer/env):
  SQUARE_ENVIRONMENT   'production' | 'sandbox' (default sandbox)
  SQUARE_ACCESS_TOKEN  account access token (shared with the other Rohde Square apps)
  SQUARE_LOCATION_ID   the XCTimer location (LGXPPYDV1GASR)
"""
import json
import logging
import os
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
        "payment_note": note,          # surfaces on the order.note — used to bind + verify
        "description": name[:255],
    }
    data = _request("POST", "/v2/online-checkout/payment-links", payload)
    return data["payment_link"]["url"]


def order_ok(order_id, expect_note_substr=None):
    """True iff the order exists, is COMPLETED, and (optionally) its note carries
    `expect_note_substr` — so a replayed / cross-event orderId can't publish the wrong
    event. Any error → False (never publish on an unverifiable order)."""
    if not order_id:
        return False
    try:
        o = _request("GET", f"/v2/orders/{order_id}").get("order", {})
        if o.get("state") != "COMPLETED":
            return False
        if expect_note_substr and expect_note_substr not in (o.get("note") or ""):
            return False
        return True
    except Exception:
        log.exception("order_ok failed for %s", order_id)
        return False
