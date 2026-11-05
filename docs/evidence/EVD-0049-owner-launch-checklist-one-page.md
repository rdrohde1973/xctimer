# EVD-0049: WP-0010 — Owner launch checklist (one page)

- **Cites:** WP-0010
- **Review:** WP-0010·R1 by Tess Ting
- **Date:** 2026-11-05T18:11:00.327Z
- **Result:** FAIL

## Command

```
grep -c 'code=FIRSTRACE' docs/marketing/LAUNCH.md docs/marketing/ads.md; grep -n 'G1\|G3\|G4' LAUNCH.md
```

## Result line

```
ads.md:0, LAUNCH.md:1 (only in the G3 "not built" row); G1-G3 listed as not built; G4 under Known Limits, not Later
```
