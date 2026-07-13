"""Track & field engine — Phase 4. Reference: ~/track/track_timer.py.

To build here:
  - meet_events (grade x gender x event), per-athlete event limit,
    athlete-centric assignment UI, carry-over from last meet.
  - Relays as school squad entries (members JSON, no bib); combined distance races.
  - Heats & lanes: random + seeded draws (sprints by best time, distance by prior
    points), lane center-out, sections for non-laned events.
  - Field events: LJ/SP 3-attempt grid (best legal); High Jump make/miss-per-bar;
    optional open-pit entry.
  - Heat sheets / meet-day packets (PDF, one heat per page) — pdfs.py.
  - AI vision scan-back: photograph filled heat sheet -> Claude reads token +
    handwritten marks -> confirm -> post + re-rank — ai.py.
  - Per-event entry grids, results, per-event + team scoring, public results.
"""
from flask import Blueprint

bp = Blueprint("track", __name__)
