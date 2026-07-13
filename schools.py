"""Schools + athletes (roster) — Phase 2.

To build here:
  - School CRUD: bib blocks (bib_start-bib_end), per-school logo.
  - Athlete CRUD (shared across sports within a district).
  - AI document import (Excel/CSV/PDF/Word -> normalized names via Claude) — ai.py.
  - Google Sheet sync (paste share link, pull roster).
  - Bib stickers (Avery 5160/5163) + bib lists (PDF) — pdfs.py.
  - Bib check (scan sticker QR / type bib -> athlete lookup).
"""
from flask import Blueprint

bp = Blueprint("schools", __name__)
