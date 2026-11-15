#!/usr/bin/env python3
"""Times survive a slow server or a dead spot at the finish line (1.131.0).

Phones stamp each start, tap and stop themselves, keep it saved, and re-send it until the
server has it. This pins what the server does with a tap that arrives late, twice, out of
order, after Stop, or from a phone whose clock is wrong.
    python scripts/test_tap_queue.py
Temp DB (XCTIMER_DB); never touches real data or the network."""
import json, os, sys, tempfile, time
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.environ["XC_MAIL_DISABLE"] = "1"
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))
sys.path.insert(0, tmp)

import xctimerpkg                                                      # noqa: E402
sys.modules["xctimer"] = xctimerpkg
from xctimerpkg import app as appmod, db, auth, clocktime             # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}


def q(sql, *a):
    conn = db.connect()
    rows = conn.execute(sql, a).fetchall()
    conn.close()
    return rows


def ex(sql, *a):
    conn = db.connect()
    rid = conn.execute(sql, a).lastrowid
    conn.commit()
    conn.close()
    return rid


def near(a, b, tol=0.6):
    return a is not None and abs(a - b) <= tol


now_ms = lambda: int(time.time() * 1000)                              # noqa: E731

# ---- 1. the rule itself --------------------------------------------------------------
NOW = datetime(2027, 9, 1, 16, 0, 0, tzinfo=timezone.utc)
ms = lambda dt: int(dt.timestamp() * 1000)                            # noqa: E731
ago = lambda s: NOW - timedelta(seconds=s)                            # noqa: E731
ed = clocktime.event_dt
assert ed(None, None, NOW) == NOW and ed("abc", None, NOW) == NOW
assert ed(ms(ago(3)), None, NOW) == ago(3)                            # an ordinary tap
assert ed(ms(ago(100)), None, NOW) == ago(100)                        # 100 s in a busy server's queue: kept
assert ed(ms(ago(400)), None, NOW) == NOW                             # 400 s with no reason given: clock is wrong
assert ed(ms(ago(400)), 400_000, NOW) == ago(400)                     # ...but the phone held it 400 s: kept
assert ed(ms(ago(1800)), 1_800_000, NOW) == ago(1800)                 # half an hour without signal
assert ed(ms(NOW + timedelta(hours=1)), 60_000, NOW) == ago(60)       # phone clock an hour fast: now - age
assert ed(ms(ago(3)), -5, NOW) == ago(3) and ed(ms(ago(3)), "x", NOW) == ago(3)
assert ed(float("nan"), None, NOW) == NOW and ed(1e30, None, NOW) == NOW
assert clocktime.stale_before(ago(10), NOW) and not clocktime.stale_before(ago(1), NOW)
assert clocktime.after_stop(NOW, ago(5)) and not clocktime.after_stop(ago(5), NOW)
print("PASS 1: a tap keeps its own time whenever that time fits how long it was held or in flight")

# ---- fixtures ------------------------------------------------------------------------
DID = ex("INSERT INTO districts (name, slug, settings_json) VALUES ('Payper','payper',?)", json.dumps({"plan": "per_meet"}))
SID = ex("INSERT INTO schools (district_id, name) VALUES (?, 'Payper North')", DID)
ATH = [ex("INSERT INTO athletes (school_id, name, grade, gender, does_xc, does_track, active) VALUES (?,?,8,'M',1,1,1)",
          SID, f"Runner {i}") for i in range(1, 5)]
COACH = ex("INSERT INTO users (district_id, email, name, role) VALUES (?,?,?,?)", DID, "coach@payper.example", "Coach", "coach")
ex("INSERT INTO user_schools (user_id, school_id) VALUES (?,?)", COACH, SID)
ex("INSERT INTO promo_codes (code, active, percent_off, first_event_only, used_count) VALUES ('FREE',1,100,0,0)")
c = application.test_client()
c.set_cookie("csrftoken", "x")
c.set_cookie(auth.SESSION_COOKIE, auth.create_session(COACH))
r = c.post("/meets", data=dict(name="Live Meet", sport="xc", date="2027-09-01", school_ids=[SID]), headers=H)
MID = int(r.headers["Location"].rsplit("/", 1)[1])
assert c.post(f"/meets/{MID}/meet-fee/redeem", json={"code": "FREE"}, headers=H).get_json()["paid"]
RID = q("SELECT id FROM races WHERE meet_id=? ORDER BY id", MID)[0][0]
BIB = [q("SELECT bib FROM meet_bibs WHERE meet_id=? AND athlete_id=?", MID, a)[0][0] for a in ATH]

post = lambda url, **j: c.post(url, json=j, headers=H)                # noqa: E731
state = lambda: c.get(f"/races/{RID}/state").get_json()               # noqa: E731
fins = lambda: [(f["seq"], round(f["elapsed"]), f["bib"]) for f in state()["finishers"]]   # noqa: E731


def begin(ago_s=600):
    """Reset, then start the race `ago_s` seconds ago, as a phone that held the start would."""
    assert post(f"/races/{RID}/reset").status_code == 200
    t0 = now_ms() - ago_s * 1000
    assert post(f"/races/{RID}/start", at=t0, age=ago_s * 1000).status_code == 200
    assert abs(state()["start_ms"] - t0) < 5
    return t0


def tap(t0, sec, cid=None, held=True):
    """A tap `sec` seconds into the race, sent now."""
    at = t0 + int(sec * 1000)
    body = {"at": at}
    if cid:
        body["cid"] = cid
    if held:
        body["age"] = now_ms() - at
    return post(f"/races/{RID}/tap", **body)


# ---- 2. late, repeated and out-of-order taps ------------------------------------------
t0 = begin()
assert near(tap(t0, 10, "a").get_json()["elapsed"], 10)               # held 590 s, still exactly 10 s
assert near(tap(t0, 30, "c").get_json()["elapsed"], 30)
j = tap(t0, 20, "b").get_json()                                       # the tap between them arrives last
assert j["seq"] == 2 and near(j["elapsed"], 20)
assert fins() == [(1, 10, None), (2, 20, None), (3, 30, None)], fins()
j = tap(t0, 20, "b").get_json()                                       # the same tap, sent again
assert j.get("duplicate") and j["seq"] == 2 and len(fins()) == 3
assert near(tap(t0, 400, held=False).get_json()["elapsed"], 400)      # no `age` (older page), 200 s late: kept
print("PASS 2: a tap that arrives late or twice lands once, in time order, with its own time")

# ---- 3. a late tap when bibs are already scanned: each bib moves onto its real time ----
t0 = begin()
for sec, cid in ((10, "a"), (30, "c"), (40, "d")):                    # the tap at 20 s is stuck on the phone
    tap(t0, sec, cid)
for b in BIB[:2]:                                                     # first two runners scanned in the chute
    assert post(f"/races/{RID}/finish", bib=b).get_json()["ok"]
assert fins() == [(1, 10, BIB[0]), (2, 30, BIB[1]), (3, 40, None)], fins()   # runner 2 on the wrong time
assert tap(t0, 20, "b").status_code == 200
assert fins() == [(1, 10, BIB[0]), (2, 20, BIB[1]), (3, 30, None), (4, 40, None)], fins()
for b in BIB[2:]:
    assert post(f"/races/{RID}/finish", bib=b).get_json()["ok"]
assert fins() == [(1, 10, BIB[0]), (2, 20, BIB[1]), (3, 30, BIB[2]), (4, 40, BIB[3])], fins()
print("PASS 3: a late tap puts every scanned runner back on the time they crossed at")

# ---- 4. Stop: the first one wins, and a tap from before it still counts ---------------
r = post(f"/races/{RID}/stop", at=t0 + 50_000, age=now_ms() - (t0 + 50_000))
assert r.status_code == 200 and abs(state()["stop_ms"] - (t0 + 50_000)) < 5
post(f"/races/{RID}/stop", at=t0 + 60_000, age=now_ms() - (t0 + 60_000))
post(f"/races/{RID}/stop")
assert abs(state()["stop_ms"] - (t0 + 50_000)) < 5, "a second stop must not move the first"
assert near(tap(t0, 45, "e").get_json()["elapsed"], 45)               # tapped before Stop, delivered after
assert tap(t0, 55, "f").status_code == 400                            # tapped after Stop
assert tap(t0, 45).status_code == 400                                 # an older page (no id) after Stop: as before
assert [f[1] for f in fins()] == [10, 20, 30, 40, 45]
print("PASS 4: the first Stop holds, and a tap made before it is still recorded")

# ---- 5. a tap left over from a race that was reset is not added to the next one -------
t0 = begin(ago_s=5)
r = tap(t0, -300, "old")
assert r.status_code == 409 and "before this race started" in r.get_json()["error"] and fins() == []
assert near(tap(t0, -1, "early").get_json()["elapsed"], 0)            # a hair before the gun counts as 0.0
print("PASS 5: a saved tap from an earlier run is refused, with a reason")

# ---- 6. scan-only finishes use the phone's time too -----------------------------------
t0 = begin()
at = t0 + 100_000
j = post(f"/races/{RID}/finish", bib=BIB[0], at=at, age=now_ms() - at).get_json()
assert j["ok"] and fins() == [(1, 100, BIB[0])], fins()
post(f"/races/{RID}/stop", at=t0 + 200_000, age=now_ms() - (t0 + 200_000))
at = t0 + 150_000                                                     # read before Stop, delivered after
assert post(f"/races/{RID}/finish", bib=BIB[1], at=at, age=now_ms() - at).get_json()["ok"]
assert post(f"/races/{RID}/finish", bib=BIB[2]).status_code == 400    # no time given after Stop: refused, as before
assert fins() == [(1, 100, BIB[0]), (2, 150, BIB[1])], fins()
print("PASS 6: a bib scan that is the finish records the moment it was read")

# ---- 7. track: the clock timer and the lane timer -------------------------------------
r = c.post("/meets", data=dict(name="Track Meet", sport="track", date="2027-04-01", school_ids=[SID]), headers=H)
TM = int(r.headers["Location"].rsplit("/", 1)[1])
assert c.post(f"/meets/{TM}/meet-fee/redeem", json={"code": "FREE"}, headers=H).get_json()["paid"]
ev = q("SELECT id FROM events WHERE name='800m'")[0][0]
ME = ex("INSERT INTO meet_events (meet_id, event_id, gender) VALUES (?,?,'M')", TM, ev)
E = [ex("INSERT INTO entries (meet_event_id, runner_id, school_id, heat, lane) VALUES (?,?,?,1,?)", ME, a, SID, i + 1)
     for i, a in enumerate(ATH)]
U = f"/meet-events/{ME}"
tstate = lambda: c.get(f"{U}/time/state?heat=1").get_json()           # noqa: E731
ttaps = lambda: [round(t["elapsed"]) for t in tstate()["taps"]]       # noqa: E731


def ttap(t0, sec, cid=None):
    at = t0 + int(sec * 1000)
    body = {"at": at, "age": now_ms() - at}
    if cid:
        body["cid"] = cid
    return post(f"{U}/time/tap?heat=1", **body)


t0 = now_ms() - 600_000
assert post(f"{U}/time/start?heat=1", at=t0, age=600_000).status_code == 200
assert abs(tstate()["start_ms"] - t0) < 5
for sec, cid in ((120, "a"), (140, "c"), (130, "b"), (130, "b")):     # late, then repeated
    assert ttap(t0, sec, cid).status_code == 200
assert ttaps() == [120, 130, 140], ttaps()
assert [t["seq"] for t in q("SELECT seq FROM track_taps WHERE meet_event_id=? ORDER BY seq", ME)] == [1, 2, 3]
post(f"{U}/time/stop?heat=1", at=t0 + 200_000, age=now_ms() - (t0 + 200_000))
post(f"{U}/time/stop?heat=1")
assert abs(tstate()["stop_ms"] - (t0 + 200_000)) < 5
assert ttap(t0, 150, "d").status_code == 200 and ttap(t0, 250, "e").status_code == 409
assert ttap(t0, 150).status_code == 409 and ttaps() == [120, 130, 140, 150]
# lane timer: one phone per lane, held taps keep their time; a tap from a reset heat is refused
at = t0 + 133_500
j = post(f"{U}/lane-finish?heat=1&lane=2", at=at, age=now_ms() - at).get_json()
assert j["ok"] and near(j["secs"], 133.5, 0.05), j
assert near(q("SELECT mark_seconds FROM results WHERE entry_id=?", E[1])[0][0], 133.5, 0.05)
assert post(f"{U}/time/reset?heat=1").status_code == 200
t1 = now_ms()
assert post(f"{U}/time/start?heat=1", at=t1).status_code == 200
r = post(f"{U}/lane-finish?heat=1&lane=2", at=at, age=now_ms() - at)
assert r.status_code == 409 and not q("SELECT 1 FROM results WHERE entry_id=?", E[1])
assert ttap(t1, -300, "old").status_code == 409 and ttaps() == []
print("PASS 7: track taps and lane taps follow the same rules")

# ---- 8. the timing pages save and re-send -------------------------------------------
page = lambda u: c.get(u).get_data(as_text=True)                      # noqa: E731
ph = page(f"/phone/race/{RID}")
assert "xctimer-sendq" in ph and "SENDQ.add('/races/'+RID+'/tap'" in ph and "SENDQ.add('/races/'+RID+'/start'" in ph
assert "SENDQ.add('/races/'+RID+'/stop'" in ph and "saved on this phone with the exact time" in ph
assert "jpost('/races/'+RID+'/tap'" not in ph                         # no tap goes out un-saved
tt = page(f"{U}/time?heat=1")
assert "SENDQ.add('/meet-events/'+RID+'/time/tap?heat='+HEAT" in tt and "SENDQ.add(QSTART" in tt and "SENDQ.add(QSTOP" in tt
ln = page(f"{U}/lanes?heat=1")
assert "__SENDQ_JS__" not in ln and "SENDQ.add('/meet-events/'+MEID+'/lane-finish" in ln and "SENDQ.add(LSTART" in ln
cam = page(f"/races/{RID}/camera")
assert "readAt(id)" in cam and "saved, trying again" in cam
cols = lambda t: [r[1] for r in q(f"PRAGMA table_info({t})")]         # noqa: E731
assert "client_id" in cols("finishers") and "client_id" in cols("track_taps")
print("PASS 8: the phone timer, track timer, lane timer and camera all keep a tap until it is delivered")
print("ALL PASS")
