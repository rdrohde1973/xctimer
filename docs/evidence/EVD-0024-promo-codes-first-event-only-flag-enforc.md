# EVD-0024: WP-0008 — Promo codes: "first event only" flag enforced per host

- **Cites:** WP-0008
- **Review:** WP-0008·R1 by Tess Ting
- **Date:** 2026-11-05T18:03:30.221Z
- **Result:** FAIL

## Command

```
grep -rn promo_redemptions --include=*.py .; git diff main...HEAD --stat | grep reap
```

## Result line

```
no matches; reap.py unchanged - redemptions not persisted, no reap test
```
