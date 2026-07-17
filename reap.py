"""Daily reaper for self-serve 'run your own fun run' events: deletes each XCTimer Web
event (and its owner login/sessions) 30 days after the event date. Run by the
xctimer-reap.timer systemd --user unit."""
import sys

sys.path.insert(0, "/home/rob")
from datetime import date
from xctimer import db
from xctimer.road import reap_web_events

con = db.connect()
n = reap_web_events(con, date.today().isoformat())
con.close()
print(f"xctimer-reap: purged {n} expired self-serve web event(s)")
