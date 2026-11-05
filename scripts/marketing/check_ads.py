#!/usr/bin/env python3
"""Count ad variants in docs/marketing/ads.md, check limits, fill in the char counts.
Usage: check_ads.py [path] [--fix]   (--fix rewrites the Chars column)
Checks: >=6 variants, primary<=125, headline<=40, CTA in {Sign Up, Learn More},
and every 'Inv n' cited exists in positioning.md's Feature Inventory.
"""
import re, sys
path = next((a for a in sys.argv[1:] if not a.startswith("--")), "docs/marketing/ads.md")
fix = "--fix" in sys.argv
lines = open(path, encoding="utf-8").read().splitlines()
pos = open("docs/marketing/positioning.md", encoding="utf-8").read()
inv = {int(m) for m in re.findall(r"^\| (\d+) \|", pos, re.M)}
LIM = {"Primary text": 125, "Headline": 40}
errs, variants, cur = [], {}, None
for i, l in enumerate(lines):
    m = re.match(r"### (V\d+):", l)
    if m: cur = m.group(1); variants[cur] = set(); continue
    if l.startswith("## "): cur = None
    if not cur or not l.startswith("|"): continue
    cells = [c.strip() for c in l.strip().strip("|").split("|")]
    if len(cells) < 4: continue
    f, copy = cells[0], cells[1].strip("`")
    variants[cur].add(f)
    if f in LIM:
        n = len(copy)
        if n > LIM[f]: errs.append(f"{cur} {f}: {n} > {LIM[f]}")
        if fix: lines[i] = re.sub(r"\| *\d+ *\| ", f"| {n} | ", l, count=1)
    if f == "CTA button" and copy not in ("Sign Up", "Learn More"):
        errs.append(f"{cur} bad CTA {copy}")
    for n in re.findall(r"Inv ([\d, ]+)", cells[3]):
        for x in re.findall(r"\d+", n):
            if int(x) not in inv: errs.append(f"{cur}: Inv {x} not in inventory")
for v, fs in variants.items():
    for need in ("Primary text", "Headline", "Description", "CTA button"):
        if need not in fs: errs.append(f"{v} missing {need}")
if len(variants) < 6: errs.append(f"only {len(variants)} variants")
if fix: open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print(f"{len(variants)} variants; {len(errs)} problems")
for e in errs: print(" -", e)
sys.exit(1 if errs else 0)
