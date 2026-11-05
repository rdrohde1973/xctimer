# XCTimer Positioning, Personas & Messaging (Fun-Run Focus)

> **Direction:** ADR-0013 (accepted) sets the primary focus: community fun-run/5K organizers, "time your own event". Schools get at most a secondary mention. It supersedes ADR-0006's segment weighting. Organic-only at $0: ADR-0007. Offer PROVISIONAL(Q-0007): first event free via a campaign promo code, then $50 per event. The 30-day trial from ADR-0009 is parked for possible future school plans. This is a plan for Rob; nothing has been published. Sources: `file:line` = this repo (worktree root); URLs fetched 2026-11-05. Evidence depth: the live pages were read in full; code was read at the route/function level for the /host flow (`road.py`), `square.py`, `reap.py`, `coursemap.py` and `waivers.py`, and by docstring and route for the rest.

## Summary

- **Primary pitch:** "Time your own event." A volunteer organizer builds a 5K or fun run on xctimer.com/host, free until they open registration, with a public sign-up page, printed bibs, phone/camera timing and live results. [src: https://xctimer.com/host] [src: road.py:1093]
- **Primary audience:** PTA/booster fundraisers, church and charity runs, running clubs, school and club fundraisers, small race directors. Adults only. [src: docs/architecture-decisions/ADR-0013-primary-campaign-focus-fun-run-organizer.md]
- **Offer (PROVISIONAL(Q-0007)):** first event free through a campaign promo code, then $50 per event. The mechanism exists: a 100%-off code publishes with no payment. [src: road.py:1306] [src: road.py:178]
- **Signup and payment already exist.** Host signup, event build, Square checkout and promo redemption are live. The funnel steps are host signup, then event built, then event published (paid or promo). [src: road.py:1143] [src: road.py:1268] [src: road.py:1306]
- **Real gaps (small, mostly marketing-side):** no fun-run landing page; no UTM capture or attribution on /host; no Pixel or other events; and a privacy-page promise of no third-party tracking that conflicts with a Pixel. [src: road.py] [src: https://xctimer.com/security]
- **Product caveats to respect in copy:** `/host` events are deleted 30 days after the event date; runner entry fees are Venmo or packet pickup, not card; there is no waiver at registration (waivers.py serves school districts only). [src: reap.py] [src: road.py:866] [src: waivers.py]
- **Timing:** spring fun runs (Mar–Jun) are planned in winter, so organic posting starts now, in Nov 2026. [src: docs/architecture-decisions/ADR-0013-primary-campaign-focus-fun-run-organizer.md]
- **Competitors:** registration platforms (RunSignup, Race Roster, Race Entry) and hiring a timing company. XCTimer's gap to fill is "registration + timing + results in one cheap, self-serve flow".
- **Rob decisions:** confirm the Q-0007 offer and the promo code value (code name and max uses); decide Pixel vs. the "no tracking" promise; approve a fun-run landing page and UTM WP.

## Feature Inventory

Led by the /host flow. Each row cites its source. "Site" rows come from the live /host page, the home page, or /security.

### A. Fun-run / community-event flow (primary)

| # | Feature | Source |
|---|---|---|
| 1 | Self-serve start at /host: event name, date, your name and email; a private manage-link is emailed; "Email my link" returns existing hosts to their event | [src: https://xctimer.com/host] [src: road.py:1093] [src: road.py:1191] |
| 2 | Build free, pay to go live: $50 per event, registration stays closed until paid | [src: https://xctimer.com/host] [src: road.py:24] [src: road.py:719] |
| 3 | Card payment through Square one-time checkout; the order is verified as COMPLETED before the event publishes | [src: square.py] [src: road.py:1268] |
| 4 | Promo codes: super admin creates codes with percent off, label, max uses; 100% publishes free with no Square payment; a partial percent charges the reduced amount | [src: road.py:178] [src: road.py:1306] |
| 5 | Venmo path: host confirms Venmo payment on an honor system (not verified) | [src: road.py:1234] |
| 6 | Public registration page with link and QR; runners enter name, age, gender, city, club and pick a race, no account | [src: road.py:849] [src: https://xctimer.com] |
| 7 | Multiple races per event (for example 5K, 10K, Fun Run) with age groups per race | [src: road.py:1470] [src: xc.py:241] |
| 8 | Optional runner entry fee, collected via the organizer's Venmo or at packet pickup (not card) | [src: road.py:866] |
| 9 | Event logo and colors on the registration page and printed bibs | [src: road.py:696] [src: https://xctimer.com] |
| 10 | Participant import by CSV, hand-add, or self-register | [src: road.py:547] |
| 11 | Printed bib stickers (Avery 5523 size, weatherproof) with camera-readable ArUco tags and the event logo | [src: road.py:733] [src: road.py:1478] |
| 12 | Phone timing: a helper taps each finisher, then scans or types the bib to attach names; no-login QR for helpers | [src: phone.py] [src: road.py:1482] |
| 13 | Finish-line camera reads ArUco bib tags | [src: road.py:480] [src: https://xctimer.com] |
| 14 | Live public results by gender and age group with a share link/QR | [src: road.py:1486] [src: xc.py:2645] |
| 15 | Course map on satellite imagery with water stations for road events; spectator fly-over | [src: coursemap.py:127] [src: https://xctimer.com] |
| 16 | AI setup assistant (chat) that guides first-time organizers through setup | [src: road.py:1492] |
| 17 | Event and owner login auto-deleted 30 days after the event date | [src: reap.py] [src: road.py:1437] |

### B. Not available to fun-run events (do not claim)

- **Waivers:** `waivers.py` is district-scoped and per athlete (district template, parent e-sign link). The /host registration form has no waiver step. Do not advertise waivers for fun runs until a WP builds it. [src: waivers.py] [src: road.py:849]
- **Online card entry fees for runners:** none; runners pay the organizer by Venmo or at pickup. [src: road.py:866]
- **Long-term results archive:** events are deleted 30 days after the date, so say "download your results" in copy. [src: reap.py]
- **Compliance and accuracy claims:** no FERPA/COPPA compliance claim (the site says only "designed with" those expectations) and no chip-mat accuracy parity claim. [src: https://xctimer.com/security]
- **Pixel and "no tracking":** the privacy page says there are no third-party ad or tracking scripts. [src: https://xctimer.com/security]

### C. Secondary: schools (one-line mention only)

XC and track meet engines, AI roster import, scoring, districts, progress cards, championship picks, parent waivers. [src: xc.py] [src: track.py] [src: schools.py] [src: tenancy.py] [src: champ.py] [src: waivers.py] The High Jump caveat stays: the site says "make/miss grid" and code supports it, but a code comment says one flow records only best height cleared; QA before any claim. [src: track.py:1252]

## Signup Funnel Today

**Funnel steps to measure (ADR-0013):** ad or post → /host → host signup → event built → event published (paid or promo). Registration and results follow, but those are the organizer's product experience, not our acquisition funnel. [src: docs/architecture-decisions/ADR-0013-primary-campaign-focus-fun-run-organizer.md]

| Step | Exists today? | Source |
|---|---|---|
| Landing page for fun-run organizers | No: the home page serves schools, districts and fun runs together; /host is a form | [src: https://xctimer.com] [src: https://xctimer.com/host] |
| Host signup (event name, date, email) | Yes, no card, no password | [src: road.py:1143] |
| Private link by email | Yes | [src: road.py:1185] |
| Event built (races, age groups, logo) | Yes | [src: road.py:1470] |
| Publish: $50 card via Square | Yes | [src: road.py:1246] [src: square.py] |
| Publish: promo code (100% = free) | Yes, super admin creates codes | [src: road.py:178] [src: road.py:1306] |
| UTM capture and attribution | No: nothing in /host stores utm_* or referrer | [src: road.py:1143] |
| Pixel / conversion events | No: none in the code, and the privacy page promises no third-party tracking | [src: https://xctimer.com/security] |
| Pricing on /host | Yes, the "$50 per event" line | [src: https://xctimer.com/host] |

**Gaps to close (checklist; each is a candidate WP, none done here):**

- [ ] **Fun-run landing page** with one message and one CTA to /host, matching the ad copy.
- [ ] **UTM capture:** record utm_source/medium/campaign on /host and tie it to the host and meet rows, so "event published" can be attributed.
- [ ] **Event stage tracking:** host created, event built (first race added), event published, with paid vs. promo recorded. Today `promo_code` is stored in event settings when redeemed. [src: road.py:1306]
- [ ] **Pixel decision:** use `Lead` on host signup and `CompleteRegistration` on publish, via Pixel plus Conversions API, but only after Rob updates the "no third-party tracking" promise or chooses server-side-only events. Without this the success measure is UTM clicks plus the manual promo-code count. [src: docs/marketing/fb-playbook.md]
- [ ] **Campaign promo code:** Rob creates one 100% code in /organizers with a label and a max-uses cap. PROVISIONAL(Q-0007).
- [ ] **Guard against promo abuse:** the cap on uses is the only limit in code. Choose a cap before posting the code publicly. [src: road.py:1282]
- [ ] **Repeat-use hook:** the fee is per event, so revenue is not recurring. Collect return events with the "Email my link" flow and a follow-up. [src: road.py:1191]
- [ ] **Schools (secondary):** coaches still have no self-serve signup; accounts are created by an admin. Leave until later. [src: admin.py:619]

## Seasonality

| Window | Organizer behavior | Move |
|---|---|---|
| Nov–Feb | Spring events (Mar–Jun) get planned: date, permit, sponsors, fundraising goals | **Start organic posting now:** planning content, "build it free" demos, first-event-free offer PROVISIONAL(Q-0007) |
| Mar–Jun | Spring fun runs, school-year-end fundraisers, charity 5Ks | Event-month content: race-day checklists, results sharing, testimonials only if Rob has real ones |
| Summer | Planning for fall runs; Turkey Trots and fall PTA runs | Second wave aimed at fall |
| Aug–Nov | Fall fun runs, PTA fall fundraisers, school XC season | Secondary school mention |
| Jan–May | Spring track season (schools) | Secondary school mention only |

Season windows come from ADR-0013 and the Boss brief; day-level timing is an assumption to validate with Rob's real users.

## Personas

Hypotheses for ad and content targeting, not research. Validate against Rob's actual hosts.

### Primary: Community fun-run / 5K organizer

**Shared:** a volunteer or small-team organizer running a one-off or annual event on little budget. Needs registration, bibs, timing and results without hiring a timing company. Fits `/host` today. [src: https://xctimer.com/host]

| Segment | Goal | Fit / objection |
|---|---|---|
| **P1. PTA / booster-club fundraiser lead** | Raise money for a school or team with a fall or spring fun run | Wants it easy for volunteers; worry: "who handles runner payments?" Entry fees go via the organizer's Venmo or at packet pickup. [src: road.py:866] |
| **P2. Church or charity run organizer** | A community 5K supporting a cause | Wants a clean sign-up page and results to share; worry: waivers (not supported at registration yet) [src: road.py:849] |
| **P3. Running-club race lead** | Club-run races with age-group results, repeat annual events | Values age-group results and bibs; worry: accuracy vs chip timing, and results kept only 30 days [src: reap.py] |
| **P4. Small race director** | A few small events per year, tight margins | Values the flat fee against timing and platform costs; likely the best long-term repeat user |

**Channels (organic only, no ad spend; ADR-0007) [src: docs/architecture-decisions/ADR-0007-campaign-starts-organic-only-at-0-ad-spe.md]:** Facebook groups for PTA, fundraising and local running communities (join and follow each group's rules; no mass posting), the product Page, short demo videos of "build an event in minutes." No contact-list targeting.

### Secondary: junior high / middle school coaches and meet hosts (short mention)

Coaches and ADs hosting XC and track meets can use the same phone timing, scoring and live results, plus school-specific rosters. One secondary line per asset, at most 20% of the calendar, per ADR-0013. [src: xc.py] [src: schools.py] [src: docs/architecture-decisions/ADR-0013-primary-campaign-focus-fun-run-organizer.md] District and AD detail is in the Feature Inventory section C.

## Pain Points & Value Props

| Pain (organizer) | Value prop | Proof |
|---|---|---|
| Hiring a timing company is expensive for a small event | Time it yourself with phones | [src: phone.py] [src: road.py:1482] |
| Registration platforms charge per-runner processing fees | Flat per-event fee; first event free via promo PROVISIONAL(Q-0007) | [src: https://xctimer.com/host] [src: road.py:1306] |
| Setup feels big for first-time volunteers | Build the event free first; AI setup helper | [src: road.py:1492] |
| Printing bibs and tracking who finished | Bib stickers; scan or type the bib to attach names | [src: road.py:733] [src: road.py:1482] |
| Runners and families keep asking for results | Live results link and QR by gender and age group | [src: road.py:1486] |
| Course questions ("where are the water stations?") | Course map, with water stations, and fly-over | [src: coursemap.py:127] |
| Volunteers need accounts or training | Helpers scan a QR, no login | [src: phone.py] |

## Positioning Statement

**For** volunteer organizers of community fun runs and 5Ks (PTA and booster fundraisers, churches and charities, running clubs, small race directors) **who** need registration, timing and results without a timing company or a big invoice, **XCTimer is** the self-serve way to **time your own event**: build it free, then open registration for a flat fee per event PROVISIONAL(Q-0007). **Unlike** hiring a timing company or stitching together a registration platform and a separate timer, **XCTimer** puts the sign-up page, bibs, phone/camera timing and live results in one place. [src: https://xctimer.com/host]

Secondary line (schools, one mention): "The same phone timing also runs school XC and track meets." [src: xc.py]

## Competitor Snapshot

Race registration and timing alternatives. Prices are only those cited; anything else needs re-checking before use. Meta policy limits comparative claims about named competitors, so ads should state XCTimer's own strengths, not attack them.

| Alternative | What it is | Where it overlaps | XCTimer's angle | Source |
|---|---|---|---|---|
| **RunSignup** | Race registration and race-director tools; its own pages describe free tools for directors and integrations with timing systems and its RaceDay app | Registration, results | One flow with built-in bibs and timing; they integrate with outside timers | [src: https://info.runsignup.com] |
| **Race Roster** | Registration platform; does not publish pricing and charges processing fees per registration transaction | Registration | Flat $50 per event PROVISIONAL(Q-0007) and no per-runner platform fee on our side | [src: https://raceroster.com/articles/how-to-price-your-registration] [src: https://us.fitgap.com/products/race-roster] |
| **Race Entry** | Free for directors; charges participants 4.97% + $1.25 per registration | Registration | Our runner entry is organizer-collected (Venmo or pickup), so no card fees but also no card checkout | [src: https://www.raceentry.com/blog/articles/race-roster-vs-race-entry] |
| **Hire a timing company** | Chip-timing providers; for example OnTime Racing's minimum is $500 for a 5K/10K up to 500 racers | Timing, results | Self-serve with phones; accuracy parity not claimed | [src: https://runsignup.com/Race/OnTimeRacing/Page/Prices] |
| **Timing company, flat-tier example** | Eastwood Running Club Timing charges a flat $1000 for a traditional 5K/10K under 200 participants | Timing | Same | [src: https://www.racedirectorshq.com/reviews/eastwood-running-club-timing-202/] |
| **Timing company, per-runner example** | State of Franklin Track Club lists $250 base plus $2.50 per runner | Timing | Same | [src: https://runsignup.com/w/SFTC/Page/TimingServices] |
| **Timing/results phone apps** | Example: PBKeeper, a phone timing app for track and XC | Phone timing | Event registration, bibs and public results in the same flow | [src: https://play.google.com/store/apps/details?id=com.pbkeeper] |

Not checked: RunSignup's current pricing page (the fetch failed) and Race Roster's actual fee schedule (unpublished). Do not quote them. School-side alternatives (Athletic.net, RaceTab, Hy-Tek) are only relevant to the secondary audience; see the prior sources in the git history of this file if needed.

## Messaging Pillars

1. **Time your own event.** No timing company, no big invoice: phones and a finish-line camera do the timing, volunteers join by QR. Proof: [src: phone.py] [src: road.py:480]
2. **Build it free, go live when you're ready.** Create the event, races and sign-up page first; open registration for a flat fee per event PROVISIONAL(Q-0007), or free with the campaign promo code. Proof: [src: https://xctimer.com/host] [src: road.py:1306]
3. **Everything in one place, results everyone can follow.** Sign-up page, bibs, timing and live results by age group on one link/QR, plus a course map. Proof: [src: road.py:849] [src: road.py:1486] [src: coursemap.py:127]

Secondary mention (one line per asset): "Schools: the same phone timing runs XC and track meets." [src: xc.py]

## Next Steps for Rob

- [ ] Confirm the Q-0007 offer: first event free with a campaign code, then $50 per event PROVISIONAL(Q-0007).
- [ ] Create the campaign promo code in /organizers (100% off, a label, a max-uses cap) PROVISIONAL(Q-0007).
- [ ] Approve WPs: fun-run landing page; UTM capture and event-stage tracking on /host.
- [ ] Decide on a Pixel vs the "no third-party tracking" promise on /security.
- [ ] Decide on handling for waivers and the 30-day deletion in organizer copy.
- [ ] Start organic posts now for spring events (Mar–Jun).
