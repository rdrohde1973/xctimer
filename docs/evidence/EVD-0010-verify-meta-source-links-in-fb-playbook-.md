# EVD-0010: WP-0006 — Verify Meta source links in fb-playbook.md

- **Cites:** WP-0006
- **Review:** WP-0006·R1 by Tess Ting
- **Date:** 2026-11-05T17:57:21.479Z
- **Result:** pass

## Command

```
python3 scripts/marketing/list_sources.py docs/marketing/fb-playbook.md + coverage check vs Source Check table
```

## Result line

```
35 file:line entries, 29 distinct URLs, 0 missing from Source Check table
```
