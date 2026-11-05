# ADR-0009: Offer is a free 30-day trial, then a monthly paid plan

- **Status:** accepted
- **Date:** 2026-11-05
- **Cites:** Q-0003, Q-0005, WP-0005

## Context

Rob answered Q-0003: "Free 30-day trial, then $X/mo". This replaces the provisional free tier with usage limits. The price and the card requirement are still open (Q-0005).

## Decision

This supersedes provisional ADR-0003. The call to action everywhere is "Start your free 30-day trial". Signup fires the Meta StartTrial event, and the paid conversion fires Subscribe. No free-forever tier and no plan-limit enforcement. The price stays PROVISIONAL(Q-0005), and so does card-up-front (default: no card).

## Consequences

The funnel spec (WP-0005) has trial-expiry handling (reminders at day 23/28/30, then a read-only lockout or a downgrade) instead of usage limits. Later code needs a Square subscription with trial support.
