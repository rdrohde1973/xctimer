#!/usr/bin/env python3
"""Public results say "not final yet and subject to change" while a meet is being run (1.134.0).
    python scripts/test_not_final.py
Temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import os, sys, tempfile
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, track, meets               # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
web = application.test_client()
NOTE = "Results are not final yet and are subject to change."


def ex(sql, *a):
    c = db.connect()
    rid = c.execute(sql, a).lastrowid
    c.commit(); c.close()
    return rid


NOW = datetime.now(timezone.utc)
iso = lambda **kw: (NOW - timedelta(**kw)).isoformat()                # noqa: E731
TODAY = NOW.astimezone(ZoneInfo("America/Denver")).strftime("%Y-%m-%d")
OLD = "2025-09-10"
DID = ex("INSERT INTO districts (name, slug) VALUES ('D','d')")


def page(tok):
    track._LIVE_CACHE.clear()
    r = web.get(f"/r/{tok}")
    assert r.status_code == 200, (tok, r.status_code)
    return r.get_data(as_text=True)


def shown(html):
    """The notice is on the page and visible."""
    assert html.count('id="notfinal"') <= 1
    return NOTE in html and 'id="notfinal" role="status" style="display:flex' in html


# --- 1. the date rule
assert meets.meet_is_today({"date": TODAY}) and not meets.meet_is_today({"date": OLD})
assert not meets.meet_is_today({"date": ""}) and not meets.meet_is_today({"date": None})
late = datetime(2027, 3, 2, 5, 30, tzinfo=timezone.utc)               # 10:30 pm on Mar 1 in Mountain time
assert meets.meet_is_today({"date": "2027-03-01"}, late) and not meets.meet_is_today({"date": "2027-03-02"}, late)
print("PASS 1: 'today' is the meet's date in Mountain time")

# --- 2. cross country
n = [0]


def xc_meet(date, races):
    n[0] += 1
    mid = ex("INSERT INTO meets (district_id, sport, name, date, public_token) VALUES (?,?,?,?,?)",
             DID, "xc", f"XC {n[0]}", date, f"xc{n[0]}")
    for i, (start, stop) in enumerate(races):
        ex("INSERT INTO races (meet_id, name, start_time, stop_time) VALUES (?,?,?,?)", mid, f"Race {i}", start, stop)
    return f"xc{n[0]}"


assert not shown(page(xc_meet(TODAY, [(None, None), (None, None)]))), "nothing has started: no results to qualify"
assert shown(page(xc_meet(TODAY, [(iso(minutes=20), None), (None, None)]))), "a race is running"
assert shown(page(xc_meet(TODAY, [(iso(hours=5), iso(hours=4, minutes=40)), (None, None)]))), "meet day, races still to come"
assert shown(page(xc_meet(OLD, [(iso(minutes=50), iso(minutes=30)), (None, None)]))), "wrong date on the meet, but it is going on now"
assert not shown(page(xc_meet(TODAY, [(iso(hours=2), iso(hours=1, minutes=40)), (iso(hours=1), iso(minutes=40))]))), \
    "every race stopped: the page already says Final"
assert not shown(page(xc_meet(OLD, [(iso(days=60), iso(days=60)), (None, None)]))), "old meet with a race never run"
html = page(xc_meet(TODAY, [(iso(minutes=5), None)]))
assert html.index('id="notfinal"') < html.index('id="livebox"'), "notice leads the page"
assert "#7a4b00" in html
print("PASS 2: XC shows the notice while races are still to come, and drops it when all are stopped or the meet is old")

# --- 3. track
EV = db.connect().execute("SELECT id FROM events WHERE name='100m'").fetchone()["id"]


def track_meet(date):
    n[0] += 1
    mid = ex("INSERT INTO meets (district_id, sport, name, date, public_token) VALUES (?,?,?,?,?)",
             DID, "track", f"Track {n[0]}", date, f"tr{n[0]}")
    meid = ex("INSERT INTO meet_events (meet_id, event_id, gender, grade) VALUES (?,?,'M','')", mid, EV)
    return mid, meid, f"tr{n[0]}"


def live(tok):
    track._LIVE_CACHE.clear()
    return web.get(f"/r/{tok}/live").get_json()["not_final"]


mid, meid, tok = track_meet(TODAY)
assert shown(page(tok)) and live(tok) is True, "meet day"
mid, meid, tok = track_meet(OLD)
html = page(tok)
assert not shown(html) and NOTE in html and 'style="display:none' in html and live(tok) is False, \
    "an old meet carries the notice hidden, ready for the live feed to show it"
assert "d.not_final?'flex':'none'" in html and "#f0b24b" in html
ex("INSERT INTO track_clocks (meet_event_id, heat, start_time) VALUES (?,1,?)", meid, iso(minutes=10))
assert shown(page(tok)) and live(tok) is True, "a clock started 10 minutes ago"
ex("UPDATE track_clocks SET start_time=?, stop_time=? WHERE meet_event_id=?", iso(hours=5), iso(hours=4, minutes=58), meid)
assert not shown(page(tok)) and live(tok) is False, "the last clock stopped five hours ago"
ex("INSERT INTO track_taps (meet_event_id, heat, seq, elapsed_seconds, created_at) VALUES (?,1,1,12.3,?)",
   meid, (NOW - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"))
assert live(tok) is True, "a finisher was tapped half an hour ago"
ex("DELETE FROM track_taps WHERE meet_event_id=?", meid)
assert live(tok) is False
ex("INSERT INTO pit_bars (meet_id, event_id, height, updated_at) VALUES (?,?,?,?)", mid, EV, "4-02", iso(minutes=45))
assert live(tok) is True, "the pit used a bar 45 minutes ago"
ex("UPDATE pit_bars SET updated_at=? WHERE meet_id=?", iso(hours=2), mid)
assert live(tok) is False and not shown(page(tok))
print("PASS 3: Track shows the notice on the meet's day or within 90 minutes of timing, and the live feed carries it")

# --- 4. signed-in results and fun runs are untouched
rid = ex("INSERT INTO meets (sport, name, date, public_token) VALUES ('road','Fun Run',?,'road1')", TODAY)
assert NOTE not in web.get("/r/road1").get_data(as_text=True)
assert NOTE not in web.get(f"/r/{tok}/results-inner").get_data(as_text=True)
print("PASS 4: the results tables themselves and fun-run pages don't carry it")
print("ALL PASS")
