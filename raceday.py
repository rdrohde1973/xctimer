"""Race-day morning email to coaches: "It's race day", the results link, their school's
bib list, and -- when the host drew a course map -- the map and driving directions.

Run by the xctimer-raceday.timer systemd --user unit early on meet mornings (Mountain
Time). Goes to coaches of every school entered in an XC meet dated today who have
actually logged in to XCTimer (an invite nobody accepted gets nothing). Practice time
trials are skipped. Each coach gets one email per meet, ever: sends are recorded in
meet_mail_log, so a rerun or a restart the same morning can't double-send.

    python raceday.py                               # today's meets, for real
    python raceday.py --dry-run                     # print who would get what
    python raceday.py --date 2026-09-30 --preview-to me@example.com
                                                    # every email, sent to one inbox, not logged
"""
import argparse
import json
import os
import sys
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

sys.path.insert(0, "/home/rob")
from xctimer import db                           # noqa: E402
from xctimer.auth import send_email             # noqa: E402

KIND = "raceday"
MT = ZoneInfo("America/Denver")


def _base():
    return os.environ.get("XC_PUBLIC_URL", "https://xctimer.com").rstrip("/")


def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS meet_mail_log (
        meet_id INTEGER NOT NULL, user_id INTEGER NOT NULL, kind TEXT NOT NULL,
        email TEXT, sent_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (meet_id, user_id, kind))""")


def course_start(m):
    """[lng, lat] of the start line of the first drawn course, or None."""
    try:
        doc = json.loads(m["course_json"] or "null") or {}
    except ValueError:
        return None
    for c in doc.get("courses") or []:
        pts = c.get("points") or []
        if len(pts) >= 2:
            return pts[0]
    return None


def todays_meets(conn, day):
    return conn.execute(
        "SELECT * FROM meets WHERE date=? AND sport='xc' AND COALESCE(time_trial,0)=0 "
        "AND public_token IS NOT NULL AND district_id IS NOT NULL ORDER BY id", (day,)).fetchall()


def recipients(conn, mid):
    """{user_id: (email, name, [school rows])} -- coaches of the meet's schools who have logged in."""
    out = {}
    for r in conn.execute(
            "SELECT u.id, u.email, u.name, s.id AS sid, s.name AS sname "
            "FROM meet_schools ms JOIN schools s ON s.id=ms.school_id "
            "JOIN user_schools us ON us.school_id=s.id JOIN users u ON u.id=us.user_id "
            "WHERE ms.meet_id=? AND u.role='coach' AND u.last_login IS NOT NULL "
            "AND COALESCE(u.is_demo,0)=0 AND u.email LIKE '%@%' ORDER BY u.id, s.name", (mid,)):
        e = out.setdefault(r["id"], (r["email"], r["name"], []))
        e[2].append((r["sid"], r["sname"]))
    return out


def bibs(conn, mid, sid):
    return conn.execute(
        "SELECT mb.bib, a.name, a.grade, a.gender FROM meet_bibs mb JOIN athletes a ON a.id=mb.athlete_id "
        "WHERE mb.meet_id=? AND a.school_id=? ORDER BY mb.bib", (mid, sid)).fetchall()


def build(conn, m, name, schools):
    base, tok = _base(), m["public_token"]
    results = f"{base}/r/{tok}"
    start = course_start(m)
    first = (name or "").split(" ")[0] or "Coach"
    td = 'style="padding:4px 10px;border-bottom:1px solid #e3e8ee"'
    th = 'style="padding:4px 10px;text-align:left;background:#12385f;color:#fff"'
    btn = ('style="display:inline-block;background:#e8622a;color:#fff;text-decoration:none;'
           'font-weight:700;padding:10px 16px;border-radius:8px;margin:0 8px 8px 0"')
    links = [f'<a {btn} href="{escape(results)}">📋 Live results</a>']
    if start:
        links.append(f'<a {btn} href="{escape(results)}/course">🗺 Course map</a>')
        maps = f"https://www.google.com/maps/dir/?api=1&destination={start[1]:.6f},{start[0]:.6f}"
        links.append(f'<a {btn} href="{escape(maps)}">🚗 Directions</a>')
    parts = [
        '<div style="font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#1b2b3a;max-width:620px">',
        f'<h2 style="margin:0 0 4px">🏃 It\'s race day!</h2>',
        f'<p style="margin:0 0 14px;font-size:16px"><b>{escape(m["name"])}</b></p>',
        f"<p>Good luck today, {escape(first)}! Results post live as runners finish — share the "
        "results link with your athletes and parents.</p>",
        f'<p>{"".join(links)}</p>',
    ]
    if start:
        parts.append('<p style="color:#5b6b7b;font-size:13px;margin-top:0">Directions go to the start line on the host\'s course map.</p>')
    for sid, sname in schools:
        rows = bibs(conn, m["id"], sid)
        parts.append(f'<h3 style="margin:18px 0 6px">{escape(sname)} — {len(rows)} runner{"s" if len(rows) != 1 else ""}</h3>')
        if not rows:
            parts.append("<p>No bibs are assigned to your school for this meet yet.</p>")
            continue
        body = "".join(
            f"<tr><td {td}><b>{r['bib']}</b></td><td {td}>{escape(r['name'] or '')}</td>"
            f"<td {td}>{escape(str(r['grade'] or ''))}</td><td {td}>{escape(r['gender'] or '')}</td></tr>"
            for r in rows)
        parts.append(f'<table style="border-collapse:collapse;font-size:14px"><tr><th {th}>Bib</th>'
                     f"<th {th}>Name</th><th {th}>Gr</th><th {th}>Sex</th></tr>{body}</table>")
    parts.append('<p style="color:#7c8b9a;font-size:12px;margin-top:22px">Sent by XCTimer to coaches of the '
                 "schools entered in this meet.</p></div>")
    return f"🏃 It's race day — {m['name']}", "".join(parts)


def run(day=None, dry_run=False, preview_to=None, meet_id=None, log=print):
    day = day or datetime.now(MT).date().isoformat()
    conn = db.connect()
    ensure_table(conn)
    sent = skipped = failed = 0
    meets = todays_meets(conn, day)
    if meet_id:
        meets = [m for m in meets if m["id"] == meet_id]
    for m in meets:
        for uid, (email, name, schools) in recipients(conn, m["id"]).items():
            if not preview_to and conn.execute(
                    "SELECT 1 FROM meet_mail_log WHERE meet_id=? AND user_id=? AND kind=?",
                    (m["id"], uid, KIND)).fetchone():
                skipped += 1
                continue
            subject, html = build(conn, m, name, schools)
            to = preview_to or email
            if dry_run:
                log(f"[dry-run] meet {m['id']} {m['name']!r} -> {email} ({', '.join(s for _, s in schools)})")
                sent += 1
                continue
            if send_email(to, subject if not preview_to else f"[preview for {email}] {subject}", html):
                sent += 1
                if not preview_to:
                    conn.execute("INSERT OR IGNORE INTO meet_mail_log (meet_id,user_id,kind,email) VALUES (?,?,?,?)",
                                 (m["id"], uid, KIND, email))
                    conn.commit()
            else:
                failed += 1
    conn.close()
    log(f"xctimer-raceday {day}: {len(meets)} meet(s), {sent} sent, {skipped} already sent, {failed} failed"
        + (" (dry run)" if dry_run else "") + (f" (preview to {preview_to})" if preview_to else ""))
    return sent, skipped, failed


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="meet date YYYY-MM-DD (default: today in Mountain Time)")
    ap.add_argument("--meet", type=int, help="only this meet id")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview-to", help="send every email to this address instead (not logged)")
    a = ap.parse_args()
    run(a.date, a.dry_run, a.preview_to, a.meet)
