"""Multi-tenancy: district scoping, switcher, scope guards (handoff §4) — Phase 1.

To build here:
  - district_id as the OUTERMOST guard on every endpoint (never trust the client).
  - Super Admin district switcher (session_active_district_id in the session);
    everyone else has a fixed district_id and never sees the picker.
  - Scope helpers ported from the old apps: user_school_ids, _can_view_*,
    _can_run_*, plus a district_id guard wrapping them.
  - active_district() / require_district() helpers used across blueprints.
"""
from flask import Blueprint

bp = Blueprint("tenancy", __name__)
