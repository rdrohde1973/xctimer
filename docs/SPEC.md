# SPEC — XCTimer Facebook Marketing

Owner: Rob Rohde · Boss: Madame Executive Eve · Started 2026-11-05

## Purpose
Plan a Facebook (Meta) marketing campaign that gets the target audience to sign up
for a free tier, evaluate the product, and convert to monthly paid plans.

## !! Critical mismatch found at kickoff (Q-0001)
The brief describes a product for **small general contractors**: project management,
**draw requests to the bank**, and client job-status updates.

What actually exists:
- **xctimer.com** and this repo are a **school cross-country / track meet manager**
  (rosters, bibs, phone timing, scoring, live results, districts, fun-run hosting with a
  one-time $50 Square fee). No contractor, construction or draw-request features.
  No pricing page, no self-serve free-tier signup (only /login, /host for fun runs,
  "Get in touch").
- The repo references a separate Rohde product **321draw** (`square.py` mirrors
  "321draw's Square subscription billing"; DEPLOY.md mentions `~/321draw`). That name
  fits construction draw requests. The domain 321draw.com is currently parked/for sale
  at GoDaddy, so its real public URL is unknown.

**Resolved 2026-11-05 (Q-0001 → ADR-0006):** Rob chose **XCTimer**. Target audiences
are junior high/middle school XC and track coaches and meet hosts, athletic directors,
district administrators, and community fun-run/5K organizers. Contractors are out of
scope. Note: XCTimer has no self-serve coach signup or subscription billing today,
so a free tier that converts to monthly paid needs code work (scoped in WP-0005).

**Owner override 2026-11-05 (ADR-0013):** Market mainly the **fun-run / "time your own
event"** flow (xctimer.com/host: build free, $50 to go live). Junior high schools get only
a secondary mention. Offer (provisional, Q-0007): first event free with a promo code,
then $50 per event. Ad spend is $0, organic only (ADR-0007).

## Use cases (whichever product is confirmed)
1. Prospect sees a Facebook/Instagram ad or organic post aimed at their pain.
2. Clicks to a landing page with one message and one call to action: start free.
3. Signs up for the free tier with no card; the signup is tracked (Meta Pixel +
   Conversions API, UTM tagging).
4. Gets onboarding nudges and evaluates; a share converts to a monthly plan.
5. Rob reads a weekly KPI sheet: reach, CTR, cost per signup, signup→active,
   active→paid, and cost per paying customer.

## Deliverables
- `docs/marketing/` — playbook, positioning and personas, ad copy and creative briefs,
  organic content calendar, landing page and funnel spec, KPI and measurement plan.
- Later, after the product is confirmed: code WPs for the landing page, free-tier
  signup and tracking events in the right repo.

## What this project refuses to do
- Spend money, create or change Meta Business/ad accounts, publish posts or ads, send
  messages, or push/deploy — all T4, Rob only.
- Invent prices, plan limits, customer names, testimonials, statistics or claims.
  Anything only Rob can supply is marked `PROVISIONAL(Q-xxxx)`.
- Promise features the product doesn't have (for example, draw requests in XCTimer).
- Scrape, buy or upload contact lists; no targeting that breaks Meta policy.
- Hardcode or commit secrets (pixel tokens, API keys).

## Open questions (see the tracker)
- ~~Q-0001 Which product?~~ Answered: XCTimer (ADR-0006)
- Q-0002 Ad budget and whether to start organic-only ($0)
- Q-0003 Free tier: what it includes, and what paid plans cost
- Q-0004 Meta Business account, Page and ad account ownership/access
