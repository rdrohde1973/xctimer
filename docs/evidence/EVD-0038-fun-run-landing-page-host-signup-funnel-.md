# EVD-0038: WP-0005 — Fun-run landing page & host signup funnel spec

- **Cites:** WP-0005
- **Review:** WP-0005·R2 by Tess Ting
- **Date:** 2026-11-05T18:07:27.069Z
- **Result:** FAIL

## Command

```
for n in 24 1093 1097 1107 1143 1306 1321 1414; do sed -n "${n}p" road.py; done  # spot-check [src: road.py:N] citations against current road.py
```

## Result line

```
HOST_FEE_CENTS is at road.py:25 (cited :24); host_start is at :1229 (cited ~:1093); host-redeem at :1507 (cited :1321); cited lines 1093/1097/1107/1143/1306/1321/1414 land on unrelated code
```
