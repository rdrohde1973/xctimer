# ADR-0013: Primary campaign focus: fun-run organizers "time your own event"; schools secondary

- **Status:** accepted
- **Date:** 2026-11-05
- **Cites:** WP-0003, WP-0004, WP-0005, Q-0007

## Context

Rob's message overrides ADR-0006's equal weighting: market mostly the fun-run piece ("time your own event"), with junior high schools mentioned but not the focus. The self-serve host flow already exists (road.py /host: build free, $50 to go live through Square, promo codes where 100% = free).

## Decision

This supersedes ADR-0006's segment weighting. The primary audience is community fun-run/5K organizers: PTAs and booster clubs, churches, charities, school and running-club fundraisers, and small race directors. The primary CTA goes to xctimer.com/host. Schools and districts get one secondary mention per asset, at most about 20% of the calendar. The offer is provisional per Q-0007: first event free via a campaign promo code, then $50 per event, and it replaces the 30-day trial and monthly plan in the fun-run messaging. Measurement: UTM on the /host link, with the funnel steps host signup → event built → event published (paid or promo).

## Consequences

WP-0003/4/5 are re-scoped. The funnel spec shrinks because signup and payment already exist; the gaps are a fun-run landing page, UTM capture and attribution, and Pixel events. Seasonality: spring fun runs (Mar–Jun) are planned in winter, so posting starts now. The trial ADR-0009 stays only for possible future school plans.
