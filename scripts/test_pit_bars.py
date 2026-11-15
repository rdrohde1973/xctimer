#!/usr/bin/env python3
"""Open pit, bar by bar (1.132.0), and the bar height on the results page (1.133.0): High Jump and Pole Vault take a bar height and up to three
O / X marks at it, and every pit screen warns when an athlete has no attempts left.
    python scripts/test_pit_bars.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import json, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, track                  # noqa: E402
from xctimerpkg.meets import assign_meet_bibs                           # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}


def q(sql, *a):
    c = db.connect()
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


# --- fixtures: a high-school meet with High Jump, Pole Vault and Discus, Boys and Girls
c = db.connect()
did = c.execute("INSERT INTO districts (name, slug, settings_json) VALUES ('HS','hs',?)",
                (json.dumps({"grades": [9, 10, 11, 12]}),)).lastrowid
su = c.execute("INSERT INTO users (email, name, role) VALUES ('root@example.com','Root','super_admin')").lastrowid
sid = c.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Liberty')", (did,)).lastrowid
aths = {}
for nm, gr, gx in (("Ann Jump", 11, "F"), ("Bea Jump", 12, "F"), ("Cy Jump", 10, "F"), ("Di Jump", 9, "F"),
                   ("Ed Throw", 12, "M"), ("Flo Throw", 10, "F")):
    aths[nm] = c.execute("INSERT INTO athletes (school_id, name, grade, gender, does_track, active) "
                         "VALUES (?,?,?,?,1,1)", (sid, nm, gr, gx)).lastrowid
mid = c.execute("INSERT INTO meets (district_id, sport, name, public_token, team_scoring, host_school_id) "
                "VALUES (?,?,?,?,1,?)", (did, "track", "Bars", "tokbars", sid)).lastrowid
c.execute("INSERT INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, sid))
c.commit(); c.close()

root = application.test_client()
root.set_cookie(auth.SESSION_COOKIE, auth.create_session(su))
root.set_cookie("csrftoken", "x")
with root.session_transaction() as s:
    s["active_district_id"] = did

ev = {r["name"]: r["id"] for r in q("SELECT id, name FROM events")}
r = root.post(f"/meets/{mid}/events", data={"event_ids": [str(ev[n]) for n in ("High Jump", "Pole Vault", "Discus")],
                                             "genders": ["M", "F"]}, headers=H)
assert r.status_code == 302
r = root.post(f"/meets/{mid}/track-settings", data={
    "hj_low": "4-00", "hj_high": "6-04", "hj_inc": "2", "pv_low": "6-00", "pv_high": "13-00", "pv_inc": "6"}, headers=H)
assert r.status_code == 302
c = db.connect(); assign_meet_bibs(c, mid); c.commit()
bib = {r["athlete_id"]: r["bib"] for r in c.execute("SELECT athlete_id, bib FROM meet_bibs WHERE meet_id=?", (mid,))}
c.close()
hjf = q("SELECT id FROM meet_events WHERE meet_id=? AND event_id=? AND gender='F'", mid, ev["High Jump"])[0]["id"]


def post(name, event, **body):
    body.update(event_id=ev[event], bib=bib[aths[name]])
    return root.post(f"/meets/{mid}/pit/post", json=body, headers=H)


def look(name, event, height=None):
    url = f"/meets/{mid}/pit/lookup?bib={bib[aths[name]]}&event={ev[event]}"
    return root.get(url + (f"&height={height}" if height else "")).get_json()


def result(name, meid=None):
    rows = q("SELECT r.mark_metric, r.place, r.attempts_json, r.dq FROM results r JOIN entries en ON en.id=r.entry_id "
             "WHERE en.meet_event_id=? AND en.runner_id=?", meid or hjf, aths[name])
    return rows[0] if rows else None


# --- 1. both pit screens carry the height selector, the three boxes and the schedule
for url in (f"/meets/{mid}/pit", f"/phone/meet/{mid}"):
    page = root.get(url).get_data(as_text=True)
    assert 'id="barsel"' in page and "Bar height now" in page and page.count('class="barbox"') == 3, url
    assert "pitPut('O')" in page and "pitPut('X')" in page and "pitPut('F')" not in page, url
    assert "Best height cleared" not in page and "pitwarn" in page, url
    bars = json.loads(page.split("PIT_BARS=", 1)[1].split(", PIT_NOW=", 1)[0])
    hj = bars[str(ev["High Jump"])]
    assert hj[0] == "4-00" and hj[-1] == "6-04" and len(hj) == 15, hj       # the whole schedule, not one division's ten
    assert bars[str(ev["Pole Vault"])][:2] == ["6-00", "6-06"] and str(ev["Discus"]) not in bars
print("PASS 1: laptop console and phone Pit tab both offer the bar schedule and three O/X boxes")

# --- 2. marks at a height, added to as the jumper comes back
r = post("Ann Jump", "High Jump", height="4-06", marks=["O"]); assert r.status_code == 200, r.data
r = post("Ann Jump", "High Jump", height="4-08", marks=["X"]); j = r.get_json()
assert r.status_code == 200 and j["best"] == "4-06" and j["marks"] == "X" and j["out"] is None, j
lk = look("Ann Jump", "High Jump", "4-08")
assert lk["bar"] and lk["marks"] == "X" and lk["warning"] is None and lk["grid"] == [["4-06", "O"], ["4-08", "X"]], lk
r = post("Ann Jump", "High Jump", height="4-08", marks=["X", "X", "O"]); j = r.get_json()
assert j["best"] == "4-08" and j["marks"] == "XXO" and j["summary"] == "4-06 O · 4-08 XXO", j
row = result("Ann Jump")
assert row["mark_metric"] == 56.0 and json.loads(row["attempts_json"]) == {"4-06": "O", "4-08": "XXO"}, tuple(row)
r = post("Ann Jump", "High Jump", height="4-10", marks="XXX"); j = r.get_json()      # a string works too
assert j["best"] == "4-08" and j["out"] == "4-10", j
print("PASS 2: O and X are kept per height; the best is the highest bar cleared")

# --- 3. the warning when a jumper has no attempts left
lk = look("Ann Jump", "High Jump", "4-10")
assert "Completed all attempts" in lk["warning"] and "out at 4-10 (XXX)" in lk["warning"] and "Best 4-08" in lk["warning"], lk
assert "out at 4-10" in look("Ann Jump", "High Jump")["warning"]          # no height sent (older app): still warned
post("Bea Jump", "High Jump", height="4-08", marks=["O"])
lk = look("Bea Jump", "High Jump", "4-08")
assert lk["warning"] == "Completed all attempts at 4-08: cleared it (O).", lk
assert look("Bea Jump", "High Jump", "4-10")["warning"] is None           # next bar: attempts to come
post("Cy Jump", "High Jump", height="4-00", marks=["X", "X", "X"])
lk = look("Cy Jump", "High Jump", "4-00")
assert "out at 4-00 (XXX)" in lk["warning"] and "No height cleared" in lk["warning"], lk
assert result("Cy Jump")["mark_metric"] is None and result("Cy Jump")["place"] is None
assert look("Di Jump", "High Jump", "4-00")["warning"] is None
print("PASS 3: a jumper who cleared the bar, or is out, shows a warning when the bib is typed")

# --- 4. what the server refuses
for body, want in (({"height": "4-06", "marks": ["O", "X"]}, "Nothing can follow"),
                   ({"height": "4-06", "marks": ["X", "X", "X", "O"]}, "three attempts"),
                   ({"height": "4-06", "marks": ["P"]}, "Use O"),
                   ({"height": "4-06", "marks": ["X", "F"]}, "Use O"),
                   ({"height": "", "marks": ["O"]}, "Pick the bar height"),
                   ({"height": "4-06", "marks": []}, "Enter O or X")):
    r = post("Di Jump", "High Jump", **body)
    assert r.status_code == 400 and want in r.get_json()["error"], (body, r.data)
assert result("Di Jump") is None
print("PASS 4: a mark after an O, a fourth attempt, other letters and a missing height are refused")

# --- 5. a height outside the schedule joins that division's bars; the event page shows it
before = json.loads(q("SELECT bar_heights FROM meet_events WHERE id=?", hjf)[0]["bar_heights"])
assert "3-10" not in before and len(before) == 10
r = post("Di Jump", "High Jump", height="3 10", marks=["X", "O"]); j = r.get_json()
assert r.status_code == 200 and j["height"] == "3-10" and j["best"] == "3-10", j
after = json.loads(q("SELECT bar_heights FROM meet_events WHERE id=?", hjf)[0]["bar_heights"])
assert after == ["3-10"] + before, after
page = root.get(f"/meet-events/{hjf}").get_data(as_text=True)
assert '"3-10": "XO"' in page and '"4-08": "XXO"' in page
print("PASS 5: an off-schedule height is added to the division's bars and shows in the event grid")

# --- 6. taking a height back off
r = post("Di Jump", "High Jump", height="3-10", marks=[], clear=True); assert r.status_code == 200, r.data
assert result("Di Jump") is None
post("Bea Jump", "High Jump", height="4-10", marks=["X"])
r = post("Bea Jump", "High Jump", height="4-10", marks=[], clear=True)
assert json.loads(result("Bea Jump")["attempts_json"]) == {"4-08": "O"} and r.get_json()["best"] == "4-08"
print("PASS 6: a height entered against the wrong bib can be removed")

# --- 7. a result that only held a best height keeps it when the pit adds a bar
c = db.connect()
eid = c.execute("SELECT id FROM entries WHERE meet_event_id=? AND runner_id=?", (hjf, aths["Di Jump"])).fetchone()["id"]
c.execute("INSERT INTO results (entry_id, mark_metric, attempts_json, dq) VALUES (?,?,?,1)",
          (eid, 50.0, json.dumps({"misses": 2})))
c.commit(); c.close()
assert look("Di Jump", "High Jump", "4-04")["grid"] == [["4-02", "O"]]
r = post("Di Jump", "High Jump", height="4-04", marks=["X", "X"]); assert r.status_code == 200, r.data
row = result("Di Jump")
assert json.loads(row["attempts_json"]) == {"4-02": "O", "4-04": "XX"} and row["mark_metric"] == 50.0 and row["dq"] == 1
print("PASS 7: an earlier best height is kept as a cleared bar, and a DQ stays on")

# --- 8. the app's older pit screen (best height only) still works and gets a list back
r = post("Bea Jump", "High Jump", attempts=["4 10"]); j = r.get_json()
assert r.status_code == 200 and j["best"] == "4-10", j
assert json.loads(result("Bea Jump")["attempts_json"]) == {"4-08": "O", "4-10": "O"}
lk = look("Bea Jump", "High Jump")
assert lk["attempts"] == ["4-10"] and lk["best"] == "4-10", lk
r = post("Bea Jump", "High Jump", attempts=["4 08"])                        # corrected down
assert json.loads(result("Bea Jump")["attempts_json"]) == {"4-08": "O"} and r.get_json()["best"] == "4-08"
assert post("Bea Jump", "High Jump", attempts=["", "", ""]).status_code == 400
print("PASS 8: the older best-height screen still records, and can correct a height down")

# --- 9. places: same best height shares the place
post("Cy Jump", "High Jump", height="4-00", marks=[], clear=True)
post("Cy Jump", "High Jump", height="4-08", marks=["X", "X", "O"])
pl = {n: result(n)["place"] for n in ("Ann Jump", "Bea Jump", "Cy Jump")}
assert pl == {"Ann Jump": 1, "Bea Jump": 1, "Cy Jump": 1}, pl
print("PASS 9: jumpers with the same best height share the place")

# --- 10. three-attempt events: warning once all three are in
disc_m = q("SELECT id FROM meet_events WHERE meet_id=? AND event_id=? AND gender='M'", mid, ev["Discus"])[0]["id"]
post("Ed Throw", "Discus", attempts=["98-04", "F", ""])
lk = look("Ed Throw", "Discus")
assert lk["warning"] is None and lk["attempts"] == ["98-04", "F", ""] and "bar" not in lk, lk
post("Ed Throw", "Discus", attempts=["98-04", "F", "104-11"])
lk = look("Ed Throw", "Discus")
assert lk["warning"] == "Completed all 3 attempts. Best 104-11.", lk
post("Flo Throw", "Discus", attempts=["F", "F", "F"])
assert look("Flo Throw", "Discus")["warning"] == "Completed all 3 attempts. No legal mark."
assert look("Flo Throw", "High Jump", "4-00")["warning"] is None           # a different event: nothing on file
assert json.loads(result("Ed Throw", disc_m)["attempts_json"]) == ["98-04", "F", "104-11"]
print("PASS 10: Discus warns after the third attempt, and not before")

# --- 11. the bar height the pit is at shows on the results page
inner = root.get("/r/tokbars/results-inner").get_data(as_text=True)
assert "Bar height now" in inner and "Bar now 4-08" in inner and "Pole Vault<b" not in inner, "bar now missing"
assert look("Ann Jump", "High Jump", "4-08")["bar_now"] == "4-08"
r = root.post(f"/meets/{mid}/pit/bar", json={"event_id": ev["Pole Vault"], "height": "9 6"}, headers=H)
assert r.status_code == 200 and r.get_json()["height"] == "9-06", r.data
r = root.post(f"/meets/{mid}/pit/bar", json={"event_id": ev["High Jump"], "height": "4-10"}, headers=H)   # raised
inner = root.get("/r/tokbars/results-inner").get_data(as_text=True)
card = inner.split('id="barnowcard"', 1)[1].split("</div>", 1)[0]
assert "High Jump<b" in card and ">4-10</b>" in card and "Pole Vault<b" in card and ">9-06</b>" in card, card
assert "Bar now 4-10" in inner and "Bar now 4-08" not in inner
assert "Bar height now" in root.get("/r/tokbars").get_data(as_text=True)
page = root.get(f"/meets/{mid}/pit").get_data(as_text=True)
now = json.loads(page.split("PIT_NOW=", 1)[1].split(";\n", 1)[0])
assert now == {str(ev["High Jump"]): "4-10", str(ev["Pole Vault"]): "9-06"}, now
api = {f["name"]: f for f in root.get(f"/phone/api/meets/{mid}/track").get_json()["field_events"]}
assert api["High Jump"]["bar_now"] == "4-10" and api["Discus"]["bar_now"] is None and api["Pole Vault"]["bars"][0] == "6-00"
for body in ({"event_id": ev["Discus"], "height": "4-10"}, {"event_id": ev["High Jump"], "height": "tall"},
             {"event_id": ev["High Jump"], "height": "40-00"}, {"height": "4-10"}):
    assert root.post(f"/meets/{mid}/pit/bar", json=body, headers=H).status_code == 400, body
anon = application.test_client()
assert anon.post(f"/meets/{mid}/pit/bar", json={"event_id": ev["High Jump"], "height": "5-00"},
                 headers=H).status_code in (302, 401, 403)
# a bar nobody has touched for 90 minutes is no longer "now"
c = db.connect()
c.execute("UPDATE pit_bars SET updated_at=? WHERE meet_id=? AND event_id=?",
          ("2020-01-01T00:00:00+00:00", mid, ev["High Jump"]))
c.commit(); c.close()
inner = root.get("/r/tokbars/results-inner").get_data(as_text=True)
assert "Bar now" not in inner and "High Jump<b" not in inner and ">9-06</b>" in inner
post("Di Jump", "High Jump", height="4-06", marks=["O"])                    # a mark at a height makes it current again
assert "Bar now 4-06" in root.get("/r/tokbars/results-inner").get_data(as_text=True)
print("PASS 11: the results page shows the bar height now, follows a raise, and drops a stale one")

# --- 12. helpers
assert track._bar_done("XO") and track._bar_done("XXX") and not track._bar_done("XX") and not track._bar_done("")
assert track._bar_out({"4-00": "XXX", "4-02": "XXX"}) == "4-02" and track._bar_out({"4-00": "XXO"}) is None
assert track._bar_key(["4-2", "4-04"], 50.0) == "4-2" and track._bar_key([], 50.0) == "4-02"
print("PASS 12: helper rules")
print("ALL PASS")
