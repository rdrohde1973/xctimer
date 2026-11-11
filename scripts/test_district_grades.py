#!/usr/bin/env python3
"""Per-district grade list (1.110.5). Run with a Python that has Flask installed:
    python scripts/test_district_grades.py
Uses a temp DB (XCTIMER_DB); never touches real data. Exit 0 on success."""
import json, os, re, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
os.environ["XCTIMER_DB"] = os.path.join(tmp, "t.db")
os.symlink(ROOT, os.path.join(tmp, "xctimerpkg"))      # repo dir is the package; give it an importable name
sys.path.insert(0, tmp)

from xctimerpkg import app as appmod, db, auth, tenancy                # noqa: E402
application = appmod.create_app()
application.config["TESTING"] = True
db.init_db()

P = tenancy.parse_grades
assert P("7-12") == [7, 8, 9, 10, 11, 12] and P("9,10,11,12") == [9, 10, 11, 12]
assert P("6-8, 10") == [6, 7, 8, 10] and P(" 12 , 9 ") == [9, 12] and P("7–9") == [7, 8, 9]
assert P("") is None and P("abc") is None and P("0-9") is None and P("9-13") is None and P("9-7") is None
assert tenancy.grades_span([7, 8, 9, 10, 11, 12]) == "7-12" and tenancy.grades_span([6, 8, 9]) == "6, 8, 9"
print("PASS 1: grade list parsing and labels")

conn = db.connect()
jh = conn.execute("INSERT INTO districts (name, slug) VALUES ('Junior High District','jh')").lastrowid
hs = conn.execute("INSERT INTO districts (name, slug, settings_json) VALUES ('High School District','hs',?)",
                  (json.dumps({"mask_public": False}),)).lastrowid
su = conn.execute("INSERT INTO users (email, name, role) VALUES ('root@example.com','Root','super_admin')").lastrowid
coach_sid = conn.execute("INSERT INTO schools (district_id, name) VALUES (?, 'Liberty')", (hs,)).lastrowid
da = conn.execute("INSERT INTO users (district_id, email, name, role) VALUES (?, 'da@example.com','DA','district_admin')",
                  (hs,)).lastrowid
meets = {}
for did in (jh, hs):
    meets[did] = conn.execute("INSERT INTO meets (district_id, sport, name, public_token, team_scoring) "
                              "VALUES (?,?,?,?,1)", (did, "track", f"Track {did}", f"tok{did}")).lastrowid
conn.commit()


def client(uid):
    c = application.test_client()
    c.set_cookie(auth.SESSION_COOKIE, auth.create_session(uid))
    c.set_cookie("csrftoken", "x")
    return c


def boxes(c, mid):
    html = c.get(f"/meets/{mid}").get_data(as_text=True)
    return [int(x) for x in re.findall(r'name="grades" value="(\d+)"', html)], html


def settings(did):
    return json.loads(db.connect().execute("SELECT settings_json FROM districts WHERE id=?", (did,)).fetchone()[0] or "{}")


root = client(su)
assert tenancy.district_grades(hs) == [6, 7, 8, 9] and tenancy.custom_grades(hs) is None
with root.session_transaction() as s:
    s["active_district_id"] = hs
assert boxes(root, meets[hs])[0] == [6, 7, 8, 9]
print("PASS 2: a district with no setting keeps the 6-9 default")

r = root.post(f"/districts/{hs}/grades", data={"grades": "7-12"}, headers={"X-CSRF-Token": "x"})
assert r.status_code == 302, r.status_code
assert settings(hs) == {"mask_public": False, "grades": [7, 8, 9, 10, 11, 12]}, settings(hs)
got, html = boxes(root, meets[hs])
assert got == [7, 8, 9, 10, 11, 12], got
assert "10th</label>" in html and "12th</label>" in html
print("PASS 3: super admin sets 7-12; other settings kept; track form offers 7th-12th")

with root.session_transaction() as s:
    s["active_district_id"] = jh
assert boxes(root, meets[jh])[0] == [6, 7, 8, 9] and settings(jh) == {}
print("PASS 4: the other district is untouched")

# Events really get created for the new grades, and a gender-only event still takes everyone.
with root.session_transaction() as s:
    s["active_district_id"] = hs
eid = db.connect().execute("SELECT id FROM events WHERE name='100m'").fetchone()[0]
r = root.post(f"/meets/{meets[hs]}/events", data={"event_ids": str(eid), "genders": ["M", "F"],
              "grades": ["10", "11", "12"]}, headers={"X-CSRF-Token": "x"})
assert r.status_code == 302
rows = db.connect().execute("SELECT gender, grade FROM meet_events WHERE meet_id=? ORDER BY gender, grade",
                            (meets[hs],)).fetchall()
assert [tuple(x) for x in rows] == [("F", 10), ("F", 11), ("F", 12), ("M", 10), ("M", 11), ("M", 12)], [tuple(x) for x in rows]
html = root.get(f"/meets/{meets[hs]}").get_data(as_text=True)
assert "Girls&nbsp;7-12 then Boys&nbsp;7-12" in html
print("PASS 5: 10th-12th grade events are created and stored as numbers (sort 10 after 9)")

r = root.post(f"/districts/{hs}/grades", data={"grades": "9-13"}, headers={"X-CSRF-Token": "x"})
assert r.status_code == 400 and settings(hs)["grades"] == [7, 8, 9, 10, 11, 12]
r = client(da).post(f"/districts/{hs}/grades", data={"grades": "6-9"}, headers={"X-CSRF-Token": "x"})
assert r.status_code in (302, 403) and settings(hs)["grades"] == [7, 8, 9, 10, 11, 12], r.status_code
print("PASS 6: bad input rejected; a district admin cannot change it")

r = root.post(f"/districts/{hs}/grades", data={"grades": ""}, headers={"X-CSRF-Token": "x"})
assert r.status_code == 302 and "grades" not in settings(hs) and tenancy.district_grades(hs) == [6, 7, 8, 9]
print("PASS 7: blank clears the setting back to the default")

page = root.get("/districts").get_data(as_text=True)
assert page.count('/grades"') == 2 and "<th>Grades</th>" in page
print("PASS 8: Districts page shows the Grades control for each district")

# Roster hints follow the district.
root.post(f"/districts/{hs}/grades", data={"grades": "9-12"}, headers={"X-CSRF-Token": "x"})
html = root.get(f"/schools/{coach_sid}").get_data(as_text=True)
assert "Multiple choice: 9, 10, 11, 12" in html, re.findall(r"Multiple choice: [\d, ]+", html)
import io, openpyxl                                                  # noqa: E402
wb = openpyxl.load_workbook(io.BytesIO(root.get("/roster-template.xlsx").data))
tips = " ".join(str(c.value) for c in wb["Instructions"]["A"])
assert "(9, 10, 11, 12)" in tips, tips[:200]
print("PASS 9: Google Form guide and Excel template list the district's grades")
print("ALL PASS")
