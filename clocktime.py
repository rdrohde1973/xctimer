"""When a start, tap or stop really happened (1.131.0).

Every timing phone stamps the moment of the gun or the tap itself, in server-clock terms
(each phone measures its offset from the server every few seconds). The phone then sends that stamp,
so a slow server or a weak signal at the finish line can't move a runner's time.

Phones also keep each start, tap and stop saved on the phone and re-send it until the
server confirms it (ui.SENDQ_JS). A re-sent tap carries `age`, the milliseconds the phone
has been holding it. The stamp is checked against that:

  * the event happened at about (now - age - time in flight);
  * a stamp that fits that window (allowing FUTURE_SLACK for clock error and
    TRANSIT_MAX for a slow send) is kept exactly;
  * a stamp that doesn't fit means the phone's clock is wrong, so the best estimate,
    now - age, is used instead.

A page loaded before 1.131.0 sends no `age`, which is treated as 0.
"""
from datetime import datetime, timedelta, timezone

FUTURE_SLACK = 15.0      # s a stamp may sit ahead of where it should be (phone clock error)
TRANSIT_MAX = 300.0      # s one send may spend in flight or waiting in a busy server's queue
HOLD_MAX = 12 * 3600.0   # s a phone may hold a tap; anything older is treated as nonsense


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def event_dt(at_ms, age_ms=None, now=None):
    """The moment an event happened, as an aware UTC datetime."""
    now = now or datetime.now(timezone.utc)
    age = _num(age_ms)
    age = min(max(age / 1000.0, 0.0), HOLD_MAX) if age is not None else 0.0
    best = now - timedelta(seconds=age)
    at = _num(at_ms)
    if at is None:
        return best
    try:
        dt = datetime.fromtimestamp(at / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return best
    lag = (best - dt).total_seconds()          # time in flight, if the phone's clock is right
    if -FUTURE_SLACK <= lag <= TRANSIT_MAX + FUTURE_SLACK:
        return dt
    return best


def stale_before(dt, start, slack=2.0):
    """True when a tap is from before this race's start, i.e. from an earlier run that was
    reset or restarted. A tap a hair before the gun (slack) still counts as 0.0."""
    return bool(start) and (start - dt).total_seconds() > slack


def after_stop(dt, stop, slack=0.5):
    """True when a tap is later than the race's stop, so it isn't part of this race."""
    return bool(stop) and (dt - stop).total_seconds() > slack
