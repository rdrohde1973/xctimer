"""Claude-powered AI features — Phases 2/4/5. Reference: both old apps.

Uses ANTHROPIC_API_KEY; model from XC_CLAUDE_MODEL (defaults to a Sonnet-class model).
To build here (port from the old apps):
  - _claude_chat: thin Messages API wrapper.
  - _normalize_roster: AI document import (Excel/CSV/PDF/Word -> normalized athletes).
  - _vision_read_sheet: photograph a filled heat sheet -> token + handwritten marks.
  - Insights digest builders + /api/insights/ask (school-scoped + district-wide Q&A).
    NB (handoff §11): Timer role does NOT get the insights chatbot.
"""
import os

CLAUDE_MODEL = os.environ.get("XC_CLAUDE_MODEL", "claude-sonnet-5")
