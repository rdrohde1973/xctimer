#!/usr/bin/env python3
"""Lint a marketing markdown doc. Usage:
  check_docs.py <file.md> --require "Heading A" --require "Heading B"
Exit 0 if clean, else print file:line: reason per violation and exit 1.
"""
import argparse
import re
import sys

PROV = re.compile(r"PROVISIONAL\(Q-\d{4}\)")
SRC = re.compile(r"\[src:\s*[^\]]+\]")
STAT = re.compile(
    r"\$\s?\d"                                   # dollar amounts
    r"|\d(?:[\d,.]*\d)?\s?%"                     # percentages
    r"|\b\d[\d,]*\+?\s+(?:\w+\s+)?(?:customers?|users?|clients?|contractors?|teams?|companies|businesses)\b",
    re.I,
)
LEFTOVER = re.compile(r"\b(?:TODO|TBD|XXX)\b")
HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")


def norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def check(path, required):
    errs = []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()

    headings = {norm(m.group(1)) for l in lines if (m := HEADING.match(l))}
    for req in required:
        if norm(req) not in headings:
            errs.append((1, f"missing required heading '{req}'"))

    if not any(re.match(r"^##\s+Summary\s*$", l) for l in lines[:20]):
        errs.append((1, "file must have a '## Summary' section within the first 20 lines"))

    for i, line in enumerate(lines, 1):
        if STAT.search(line) and not (PROV.search(line) or SRC.search(line)):
            errs.append((i, "statistic/price without PROVISIONAL(Q-NNNN) or [src: ...] on the same line"))
        if LEFTOVER.search(PROV.sub("", line)):
            errs.append((i, "leftover TODO/TBD/XXX (use PROVISIONAL(Q-NNNN) instead)"))
    return sorted(errs)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("file")
    ap.add_argument("--require", action="append", default=[], metavar="HEADING")
    a = ap.parse_args()
    try:
        errs = check(a.file, a.require)
    except OSError as e:
        print(f"{a.file}:1: cannot read file: {e}")
        return 1
    for ln, msg in errs:
        print(f"{a.file}:{ln}: {msg}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
