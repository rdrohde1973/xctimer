"""Demo mode + public privacy helpers (handoff §8).

- anon_name: deterministic md5 -> fake name, for demo accounts (never exposes
  real students while showcasing).
- mask_name: "Sarah Dawson" -> "S Daws" (initial + first 4 of surname) for
  public results.
- display: apply the right transform given a mode ('anon' | 'mask' | None).
"""
import hashlib

_FIRST = ["Alex", "Sam", "Jordan", "Casey", "Riley", "Taylor", "Morgan", "Jamie",
          "Avery", "Quinn", "Reese", "Rowan", "Skyler", "Dakota", "Emerson", "Finley",
          "Harper", "Kendall", "Logan", "Parker", "Sage", "Blake", "Devon", "Hayden"]
_LAST = ["Rivers", "Stone", "Hill", "Woods", "Lane", "Brooks", "Frost", "Vale",
         "Marsh", "Reed", "Cross", "Fields", "Gray", "Hale", "Nash", "Pike",
         "Rhodes", "Snow", "Wells", "York", "Beck", "Dale", "Finch", "Grove"]


def anon_name(real):
    if not real:
        return "Athlete"
    h = int(hashlib.md5(real.encode("utf-8")).hexdigest(), 16)
    return f"{_FIRST[h % len(_FIRST)]} {_LAST[(h // 131) % len(_LAST)]}"


def mask_name(real):
    """'Robert Rohde' -> 'r.rohd' (first initial + first 4 of surname, lowercased)."""
    parts = (real or "").split()
    if not parts:
        return ""
    return f"{parts[0][0].lower()}.{parts[-1][:4].lower()}"


def display(name, mode):
    if mode == "anon":
        return anon_name(name)
    if mode == "mask":
        return mask_name(name)
    return name or ""


def public_ident(name, bib, mode):
    """How to identify an athlete on public results, per the meet's setting.
    mode: 'bib' -> '#247' | 'mask' -> 'r.rohd' | 'anon' -> fake | None -> full name."""
    if mode == "bib":
        return f"#{bib}" if bib else "—"
    return display(name, mode)


def mode_for(principal):
    """The name transform for an authenticated view."""
    return "anon" if principal and getattr(principal, "is_demo", False) else None
