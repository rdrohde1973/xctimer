# ADR-0014: Fun-run offer: first event free via promo code, then $50 per event

- **Status:** accepted
- **Date:** 2026-11-05
- **Cites:** Q-0007, WP-0008

## Context

Rob answered Q-0007: a promo code for the first event. Today promo codes (road.py add_promo_code / host_redeem / _consume_promo) only have a global max_uses. There's no per-organizer "first event only" limit, so a public 100% code posted on Facebook could be reused to publish every event free.

## Decision

This supersedes provisional ADR-0012 and confirms it. The campaign offer is "Your first race is free with code {CODE}, then $50 per event." For the offer to be safe to publish, promo codes get an optional "first event only" flag, enforced in host_redeem: it's rejected if the redeeming account or organizer already has a published or paid host event. That's WP-0008 (T2). The code name is PROVISIONAL(Q-0008), placeholder FIRSTRACE. Rob creates the code in /organizers after WP-0008 ships to production; deploying is his (T4).

## Consequences

Marketing copy uses {CODE}=FIRSTRACE PROVISIONAL(Q-0008). The 30-day trial (ADR-0009) and monthly pricing don't apply to the fun-run campaign. Launch depends on WP-0008 merged plus Rob deploying.
