# EVD-0035: WP-0009 — UTM capture on /host signup + admin funnel report

- **Cites:** WP-0009
- **Review:** WP-0009·R1 by Tess Ting
- **Date:** 2026-11-05T18:06:49.321Z
- **Result:** pass

## Command

```
/tmp/wp8venv/bin/python scripts/test_host_attribution.py
```

## Result line

```
OK (rc=0; checks a-e, 403 for non-admin on report+CSV, script tag escaped, reap leaves rows, migration twice)
```
