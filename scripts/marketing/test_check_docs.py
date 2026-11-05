#!/usr/bin/env python3
"""Tiny test runner for check_docs.py. Exit 0 if all pass."""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_docs.py")
FIX = os.path.join(HERE, "fixtures")
REQ = ["--require", "Summary", "--require", "Offer", "--require", "Audience"]

# (fixture, expected exit, expected "file:line" suffix or None)
CASES = [
    ("pass.md", 0, None),
    ("fail_missing_heading.md", 1, ":1: missing required heading 'Audience'"),
    ("fail_price.md", 1, ":7: statistic/price"),
    ("fail_percent.md", 1, ":7: statistic/price"),
    ("fail_todo.md", 1, ":7: leftover TODO"),
    ("fail_no_summary.md", 1, ":1: file must have a '## Summary'"),
]

bad = 0
for name, code, expect in CASES:
    path = os.path.join(FIX, name)
    r = subprocess.run([sys.executable, SCRIPT, path, *REQ], capture_output=True, text=True)
    ok = r.returncode == code and (expect is None or (path + expect.split(" ")[0]) in r.stdout and expect.split(":", 2)[2] in r.stdout)
    if code == 0:
        ok = ok and r.stdout == ""
    print(("PASS" if ok else "FAIL"), name)
    if not ok:
        bad += 1
        print(r.stdout, r.stderr)
sys.exit(1 if bad else 0)
