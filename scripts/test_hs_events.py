#!/usr/bin/env python3
"""High-school event catalog (1.110.6). Run with a Python that has Flask installed:
    python scripts/test_hs_events.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, track                  # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
H = {"X-CSRF-Token": "x"}


def q(sql, *a):
    c = db.connect()
    try:
        return c.execute(sql, a).fetchall()
    finally:
        c.close()


# --- 1. catalog + migration
names = [r["name"] for r in q("SELECT name FROM events ORDER BY sort")]
assert len(names) == 25 and len(set(names)) == 25, names
hs = {r["name"] for r in q("SELECT name FROM events WHERE hs=1")}
assert hs == {e[0] for e in db.SEED_HS_EVENTS} and len(hs) == 14
assert not q("SELECT 1 FROM events WHERE hs=1 AND name IN ('100m','High Jump','Shot Put')")
c = db.connect(); c.execute("DELETE FROM events WHERE name IN ('Discus','Pole Vault')"); c.commit(); c.close()
db.init_db(); db.init_db()                                             # an older catalog gets topped up, once
assert len(q("SELECT 1 FROM events")) == 25 and len(q("SELECT 1 FROM events WHERE name='Discus'")) == 1
ev = {r["name"]: r for r in q("SELECT * FROM events")}
for new, like in (("Discus", "Shot Put"), ("Triple Jump", "Long Jump"), ("Pole Vault", "High Jump"),
                  ("110m Hurdles", "100m"), ("4x800m Relay", "4x400m Relay")):
    for col in ("kind", "unit", "scoring_order"):
        assert ev[new][col] == ev[like][col], (new, like, col)
print("PASS 1: 14 high-school events added once, each typed like its sibling")

# --- fixtures: one junior-high district, one high-school district
c = db.connect()
jh = c.execute("INSERT INTO districts (name, slug) VALUES ('JH','jh')").lastrowid
hsd = c.execute("INSERT INTO districts (name, slug, settings_json) VALUES ('HS','hs',?)",
                (json.dumps({"grades": [9, 10, 11, 12]}),)).lastrowid
su = c.execute("INSERT INTO users (email, name, role) VALUES ('root@example.com','Root','super_admin')").lastrowid
sid = c.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Liberty')", (hsd,)).lastrowid
aths = {}
for nm, gr, gx in (("Ann Vault", 11, "F"), ("Bea Vault", 12, "F"), ("Cal Throw", 10, "M"), ("Dee Throw", 12, "M")):
    aths[nm] = c.execute("INSERT INTO athletes (school_id, name, grade, gender, does_track, active) "
                         "VALUES (?,?,?,?,1,1)", (sid, nm, gr, gx)).lastrowid
meets = {}
for did in (jh, hsd):
    meets[did] = c.execute("INSERT INTO meets (district_id, sport, name, public_token, team_scoring, host_school_id) "
                           "VALUES (?,?,?,?,1,?)", (did, "track", f"Track {did}", f"tok{did}",
                                                    sid if did == hsd else None)).lastrowid
mid = meets[hsd]
c.execute("INSERT INTO meet_schools (meet_id, school_id) VALUES (?,?)", (mid, sid))
c.commit(); c.close()

root = application.test_client()
root.set_cookie(auth.SESSION_COOKIE, auth.create_session(su))
root.set_cookie("csrftoken", "x")


def as_district(did):
    with root.session_transaction() as s:
        s["active_district_id"] = did


def offered(m):
    html = root.get(f"/meets/{m}").get_data(as_text=True)
    ids = {int(x) for x in re.findall(r'name="event_ids" value="(\d+)"', html)}
    return {r["name"] for r in q("SELECT id, name FROM events") if r["id"] in ids}, html


as_district(jh)
got, html = offered(meets[jh])
assert got == {e[0] for e in db.SEED_EVENTS}, got
assert "Pole Vault bar schedule" not in html and 'value="3-06"' in html and 'value="5-06"' in html
print("PASS 2: a junior-high district still sees the original 11 events and bar defaults")

as_district(hsd)
got, html = offered(mid)
assert got == set(names), set(names) - got
assert "Pole Vault bar schedule" in html and 'name="hj_low" value="4-00"' in html and 'name="hj_high" value="6-04"' in html
print("PASS 3: a high-school district sees all 25, a Pole Vault schedule, and taller High Jump defaults")

# --- 4. add ungraded (Varsity-style) events
want = ["Pole Vault", "High Jump", "Discus", "Shot Put", "Triple Jump", "110m Hurdles", "100m Hurdles",
        "4x800m Relay", "4x200m Relay", "Sprint Medley Relay", "1500m"]
r = root.post(f"/meets/{mid}/events", data={"event_ids": [str(ev[n]["id"]) for n in want],
                                             "genders": ["M", "F"]}, headers=H)
assert r.status_code == 302
me = {(r["ename"], r["gender"]): r for r in q(
    "SELECT me.*, e.name AS ename FROM meet_events me JOIN events e ON e.id=me.event_id WHERE me.meet_id=?", mid)}
assert len(me) == 22
print("PASS 4: 11 event types x Boys/Girls created with no grade")

# --- 5. bar schedules
r = root.post(f"/meets/{mid}/track-settings", data={
    "hj_low": "4-00", "hj_high": "6-04", "hj_inc": "2", "pv_low": "6-00", "pv_high": "13-00", "pv_inc": "6"}, headers=H)
assert r.status_code == 302, r.status_code
bars = {(r["ename"], r["gender"]): json.loads(r["bar_heights"] or "[]") for r in q(
    "SELECT me.gender, me.bar_heights, e.name AS ename FROM meet_events me JOIN events e ON e.id=me.event_id "
    "WHERE me.meet_id=? AND e.name IN ('High Jump','Pole Vault')", mid)}
assert bars[("Pole Vault", "F")][0] == "6-00" and bars[("Pole Vault", "F")][-1] == "10-06" and len(bars[("Pole Vault", "F")]) == 10
assert bars[("Pole Vault", "M")][0] == "8-06" and bars[("Pole Vault", "M")][-1] == "13-00"
assert bars[("High Jump", "M")][-1] == "6-04" and bars[("High Jump", "F")][0] == "4-00"
st = json.loads(q("SELECT settings_json FROM meets WHERE id=?", mid)[0][0])
assert st["pv_inc"] == 6 and st["hj_high"] == "6-04"
print("PASS 5: Pole Vault gets its own bar ladder (girls low 10, boys top 10); High Jump keeps its own")

# --- 6. bibs + pit: Discus/Triple Jump take three attempts; ungraded events take every grade
c = db.connect()
from xctimerpkg.meets import assign_meet_bibs                           # noqa: E402
assign_meet_bibs(c, mid); c.commit()
bib = {r["athlete_id"]: r["bib"] for r in c.execute("SELECT athlete_id, bib FROM meet_bibs WHERE meet_id=?", (mid,))}
c.close()
assert len(bib) == 4, bib


def pit(name, event, attempts):
    return root.post(f"/meets/{mid}/pit/post", json={"event_id": ev[event]["id"], "bib": bib[aths[name]],
                                                      "attempts": attempts}, headers=H)


before = len(q("SELECT 1 FROM meet_events WHERE meet_id=?", mid))
r = pit("Cal Throw", "Discus", ["98-04", "F", "104-11"]); assert r.status_code == 200, r.data
r = pit("Dee Throw", "Discus", ["121-07", "118-00", ""]); assert r.status_code == 200, r.data
r = pit("Dee Throw", "Triple Jump", ["38-02.5", "39-01", "F"]); assert r.status_code == 200, r.data
assert len(q("SELECT 1 FROM meet_events WHERE meet_id=?", mid)) == before, "pit split an ungraded event by grade"
res = q("SELECT a.name, r.mark_metric, r.place, r.attempts_json FROM results r JOIN entries en ON en.id=r.entry_id "
        "JOIN athletes a ON a.id=en.runner_id WHERE en.meet_event_id=? ORDER BY r.place", me[("Discus", "M")]["id"])
assert [(x["name"], x["place"]) for x in res] == [("Dee Throw", 1), ("Cal Throw", 2)], [tuple(x) for x in res]
assert abs(res[0]["mark_metric"] - (121 * 12 + 7)) < 0.01 and json.loads(res[1]["attempts_json"]) == ["98-04", "F", "104-11"]
look = root.get(f"/meets/{mid}/pit/lookup?bib={bib[aths['Cal Throw']]}&event={ev['Discus']['id']}").get_json()
assert look["found"] and look["division"] == "Boys" and look["best"] == "104-11", look
print("PASS 6: Discus and Triple Jump record three attempts; 10th and 12th graders place in one Boys event")

# --- 7. Pole Vault = High Jump grid
pv = me[("Pole Vault", "F")]["id"]
for nm in ("Ann Vault", "Bea Vault"):
    r = root.post(f"/meet-events/{pv}/entries", data={"bib": str(bib[aths[nm]])}, headers=H)
    assert r.status_code == 302 and "err=" not in r.headers["Location"], r.headers["Location"]
ent = {r["runner_id"]: r["id"] for r in q("SELECT id, runner_id FROM entries WHERE meet_event_id=?", pv)}
page = root.get(f"/meet-events/{pv}").get_data(as_text=True)
assert "hj-save" in page and "Attempts (best counts)" not in page          # bar grid, not the 3-attempt table
r = root.post(f"/meet-events/{pv}/hj-save", json={"bars": bars[("Pole Vault", "F")], "rows": [
    {"eid": ent[aths["Ann Vault"]], "marks": {"7-00": "O", "7-06": "XO", "8-00": "XXX"}},
    {"eid": ent[aths["Bea Vault"]], "marks": {"7-00": "O", "7-06": "O", "8-00": "XXO", "8-06": "XXX"}}]}, headers=H)
assert r.status_code == 200, r.data
res = q("SELECT a.name, r.mark_metric, r.place FROM results r JOIN entries en ON en.id=r.entry_id "
        "JOIN athletes a ON a.id=en.runner_id WHERE en.meet_event_id=? ORDER BY r.place", pv)
assert [(x["name"], x["mark_metric"], x["place"]) for x in res] == [("Bea Vault", 96.0, 1), ("Ann Vault", 90.0, 2)], \
    [tuple(x) for x in res]
r = pit("Ann Vault", "Pole Vault", ["8 6"]); assert r.status_code == 200, r.data   # pit: best height only
print("PASS 7: Pole Vault uses the make/miss bar grid and ranks by best height cleared")

# --- 8. heat sheets, results, phone pickers
r = root.get(f"/meet-events/{pv}/heatsheet.pdf")
assert r.status_code == 200 and r.data[:4] == b"%PDF"
r = root.get(f"/meet-events/{me[('Discus', 'M')]['id']}/heatsheet.pdf")
assert r.status_code == 200 and r.data[:4] == b"%PDF"
r = root.get(f"/meets/{mid}/heatsheets.pdf")
assert r.status_code == 200 and r.data[:4] == b"%PDF"
pub = root.get(f"/r/tok{hsd}").get_data(as_text=True)
assert "Discus" in pub and "Pole Vault" in pub and "121-07" in pub, "public results missing new events"
j = root.get(f"/phone/api/meets/{mid}/track").get_json()
fe = {f["name"]: f["hj"] for f in j["field_events"]}
assert fe == {"Triple Jump": False, "High Jump": True, "Pole Vault": True, "Shot Put": False, "Discus": False}, fe
lanes = " ".join(e["label"] for e in j["lane_events"]); taps = " ".join(e["label"] for e in j["tap_events"])
assert "110m Hurdles" in lanes and "4x200m Relay" in lanes and "4x800m Relay" in taps and "1500m" in taps \
    and "Sprint Medley Relay" in taps, (lanes, taps)
print("PASS 8: heat sheets print, public results show the new events, phone pickers route them correctly")

# --- 9. a junior-high meet's pit still makes grade divisions the old way
assert track._is_hj({"ename": "Pole Vault"}) and track._is_hj({"ename": "High Jump"}) and not track._is_hj({"ename": "Discus"})
assert track._bar_schedule({"district_id": jh, "settings_json": None}, "High Jump") == ("3-06", "5-06", 2)
assert track._bar_schedule({"district_id": hsd, "settings_json": None}, "High Jump") == ("4-00", "6-04", 2)
print("PASS 9: junior-high bar defaults unchanged")
print("ALL PASS")
