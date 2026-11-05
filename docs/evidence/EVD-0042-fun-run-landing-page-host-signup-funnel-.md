# EVD-0042: WP-0005 — Fun-run landing page & host signup funnel spec

- **Cites:** WP-0005
- **Review:** WP-0005·R3 by Tess Ting
- **Date:** 2026-11-05T18:08:54.948Z
- **Result:** pass

## Command

```
git diff main...HEAD --stat; grep _record_attribution/_first_event_violation road.py
```

## Result line

```
road.py/db.py untouched; flow claims match code (attribution at 1318/1361, first-event check at 1519, redemption log at 1524); fb-playbook CTA URL replaced with /host + UTMs
```
