# ADR-0017: First-party UTM attribution instead of Meta Pixel for the organic phase

- **Status:** accepted
- **Date:** 2026-11-05
- **Cites:** WP-0009, ADR-0007

## Context

The campaign is organic only at $0 (ADR-0007). Today the app captures no utm, Pixel or referrer data (WP-0003 audit). A Pixel adds third-party script, CSP and privacy work, and mainly pays off for paid ads.

## Decision

During the organic phase, attribution is first-party only: UTM tags on every Facebook link, captured on /host and stored in a host_attribution table that survives reaping. A super_admin funnel report shows signups → events created → published → FIRSTRACE redemptions by source. The Meta Pixel/CAPI is deferred to the paid phase and will need its own ADR.

## Consequences

Rob can measure organic posts without any Meta tooling. All campaign links must carry UTM tags following the convention in fb-playbook.md.
