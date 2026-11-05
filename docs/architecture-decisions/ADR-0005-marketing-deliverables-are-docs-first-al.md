# ADR-0005: Marketing deliverables are docs-first; all external actions are Rob's (T4)

- **Status:** accepted
- **Date:** 2026-11-05
- **Cites:** WP-0001, WP-0002, Q-0001

## Context

The brief asks for a Facebook campaign. Publishing, spending and creating accounts are outward-facing and irreversible. The confirmed product (Q-0001) is still unknown.

## Decision

The team writes plans, copy, creative briefs and specs as markdown under docs/marketing/, checked by scripts/marketing/check_docs.py. Every Rob-only value is marked PROVISIONAL(Q-NNNN), and every factual claim carries a [src:] tag. Code changes (landing page, free-tier signup, Pixel/CAPI events) come only after Q-0001 is answered, as separate T2 WPs with their own ADR. Meta account setup, ad launch, posting and spend are T4 and done by Rob.

## Consequences

Nothing goes public without Rob. The checker blocks invented prices and statistics. Code work waits for Q-0001.
