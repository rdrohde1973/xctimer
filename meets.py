"""Meets: CRUD, attending schools, host, sport dispatch — Phase 3+.

To build here:
  - Meet CRUD typed sport ('xc'|'track'); meet_schools (attending), host_school_id.
  - Public results token + unauthenticated page; xlsx export.
  - Meet-day no-login QR generation (handoff §11): mint/rotate/revoke timer_token,
    render the QR (qrcode lib) on the meet page.
  - Sport dispatch: route meet-day + results to xc.py or track.py by meet.sport.
"""
from flask import Blueprint

bp = Blueprint("meets", __name__)
