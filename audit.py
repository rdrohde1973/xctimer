"""Audit log (compliance Phase 3) — who viewed / changed / exported / deleted records.

A single after_request hook (registered in app.py) records every *auditable* request:
all authenticated activity plus login attempts, minus machine noise (static assets,
health checks, and the high-frequency polling endpoints). Rows live in the audit_log
table, so they ride along in the nightly encrypted NAS backup. Retention is ~13 months,
pruned lazily when a super admin opens the Console.
"""
import os
from datetime import datetime, timezone, timedelta

from flask import request, g

from . import db

RETAIN_DAYS = int(os.environ.get("XC_AUDIT_RETAIN_DAYS", "395"))   # ~13 months

# Never audit these — machine polling, health, static assets, public marketing pages.
_SKIP_EXACT = {"/healthz", "/manifest.webmanifest", "/favicon.ico",
               "/.well-known/security.txt", "/", "/security",
               "/admin/console/tail", "/admin/console/stats"}


def _skip(path):
    if path.startswith("/static/"):
        return True
    if path in _SKIP_EXACT:
        return True
    # high-frequency live/state polls (race + track consoles, public scoreboard)
    if path.endswith("/state") or path.endswith("/live") or "/time/state" in path:
        return True
    return False


def _action(method, path):
    if path == "/login":
        return "login"
    if path == "/logout":
        return "logout"
    if method == "DELETE" or path.endswith("/delete") or path.endswith("/end-season"):
        return "delete"
    if path.endswith(".xlsx") or path.endswith(".pdf") or "/export" in path:
        return "export"
    if method in ("POST", "PUT", "PATCH"):
        return "change"
    return "view"


def _ip():
    return (request.headers.get("CF-Connecting-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or "-")


def record_request(status):
    """after_request hook: write one audit row for an auditable request. Never raises,
    and ALWAYS closes its connection (a leaked write-locked connection was cascading into
    site-wide 'database is locked' 500s). Set XC_AUDIT_DISABLE=1 to turn auditing off."""
    if os.environ.get("XC_AUDIT_DISABLE"):
        return
    conn = None
    try:
        path = request.path or "-"
        method = request.method
        p = getattr(g, "principal", None)
        is_login = (path == "/login" and method == "POST")
        if (not p and not is_login) or _skip(path):
            return
        # Meet-day QR timers fire high-frequency operational taps and never touch student
        # rosters/exports — auditing each one just amplifies writes during a live meet.
        if p is not None and getattr(p, "meet_scope", None):
            return
        if p:
            actor_id = getattr(p, "id", None)
            actor_email = getattr(p, "email", None) or (
                "meet-timer" if getattr(p, "meet_scope", None) else None)
            actor_role = getattr(p, "role", None)
            district_id = getattr(p, "district_id", None)
            detail = None
        else:                                            # unauthenticated login attempt
            actor_id, actor_role, district_id = None, None, None
            actor_email = (request.form.get("email") or "").strip().lower() or None
            detail = "ok" if status in (200, 302, 303) else (
                "throttled" if status == 429 else "fail")
        conn = db.connect()
        conn.execute(
            "INSERT INTO audit_log (ts, actor_id, actor_email, actor_role, district_id, "
            "action, method, path, status, ip, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), actor_id, actor_email, actor_role,
             district_id, _action(method, path), method, path, status, _ip(), detail))
        conn.commit()
    except Exception:      # noqa: BLE001 — auditing must never break the request
        pass
    finally:
        if conn is not None:
            try:
                conn.close()          # ALWAYS release the connection/lock
            except Exception:
                pass


def prune():
    """Delete audit rows past the retention window. Called on Console load."""
    if os.environ.get("XC_AUDIT_DISABLE"):
        return
    conn = None
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)).isoformat()
        conn = db.connect()
        conn.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,))
        conn.commit()
    except Exception:      # noqa: BLE001
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ------------------------------- pricing page clicks -------------------------------
_BOT_UA = ("bot", "crawl", "spider", "slurp", "facebookexternalhit", "preview", "monitor", "curl",
           "wget", "python-requests", "headless", "lighthouse", "scan")


def note_pricing_click():
    """Record one click through to /pricing, for the Console's "unique people" tile.

    A click = a browser that arrives from one of our own pages (same-site Referer), which is
    what pressing a Pricing button looks like; a crawler or someone opening the address cold
    is not counted, nor is the Super Admin looking at their own page. People are told apart
    by a short hash of the browser's CSRF cookie (one per browser, 30 days), so no IP address
    is stored. Never raises: counting must not break the page."""
    conn = None
    try:
        from urllib.parse import urlparse
        import hashlib
        ref = urlparse(request.referrer or "")
        if not ref.hostname or ref.hostname.lower() != (request.host or "").split(":")[0].lower():
            return
        if ref.path == "/pricing":                      # a reload, not a click
            return
        ua = (request.headers.get("User-Agent") or "").lower()
        if not ua or any(b in ua for b in _BOT_UA):
            return
        p = getattr(g, "principal", None)
        if p is not None and getattr(p, "is_super", False):
            return
        tok = request.cookies.get("csrftoken") or (
            (request.headers.get("CF-Connecting-IP") or request.remote_addr or "") + "|" + ua)
        visitor = hashlib.sha256(("pricing:" + tok).encode()).hexdigest()[:16]
        conn = db.connect()
        conn.execute("INSERT INTO pricing_clicks (ts, visitor, src) VALUES (?,?,?)",
                     (datetime.now(timezone.utc).isoformat(), visitor, (ref.path or "/")[:80]))
        conn.commit()
    except Exception:  # noqa: BLE001
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def pricing_click_counts(hours):
    """(unique people in the last `hours`, unique people all time) for the Console."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    conn = db.connect()
    try:
        recent = conn.execute("SELECT COUNT(DISTINCT visitor) FROM pricing_clicks WHERE ts>=?",
                              (cutoff,)).fetchone()[0]
        total = conn.execute("SELECT COUNT(DISTINCT visitor) FROM pricing_clicks").fetchone()[0]
    finally:
        conn.close()
    return recent, total
