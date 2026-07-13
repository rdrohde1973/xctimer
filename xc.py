"""Cross-country engine — Phase 3. Reference: ~/xc-district/xc_district.py.

To build here:
  - Races + finishers; timing console (start/stop clock, tap-to-finish, live list).
  - Phone timing PWA (tap-then-assign bibs/runners after).
  - Manual bib override, DQ toggle, drag-to-reorder (times stay in slots).
  - Combined results across races (pool by fastest), by gender, by grade x gender.
  - Team scoring (drop teams <5, re-rank, sum top 5, 6th/7th displacers).
  - xlsx export (overall + boys + girls tabs).
  - Results snapshotting (freeze name/grade/gender/school onto finishers).
"""
from flask import Blueprint

bp = Blueprint("xc", __name__)
