# XCTimer Ad Copy, Creative Briefs & 4-Week Organic Calendar

> Plan for Rob; nothing is posted, published or spent. Direction: ADR-0013 (fun-run organizers first), organic-only, zero ad spend [src: ADR-0007]. Offer: ADR-0014 with the code FINAL per ADR-0016. Claims come from the Feature Inventory in `docs/marketing/positioning.md` (rows cited as "Inv #n"). Adults only; no minors are targeted or shown. Items tagged **[Rob-only]** need Rob's logins or approval.

## Summary

- **Main deliverable now: the Organic Calendar** (12 posts over 4 weeks, starting Mon 2026-11-30, timed for Dec–Feb spring-fun-run planning). The 6 Ad Variants are **for later paid phase**; ad spend is $0 [src: ADR-0007].
- **Primary audience:** community fun-run/5K organizers (PTA/booster, church/charity, running clubs, small race directors), adults only [src: ADR-0013]. At most 2 of 12 organic posts mention schools (under the 20% cap [src: ADR-0013]).
- **Offer used in copy:** "Your first race is free with code FIRSTRACE, then $50 per event." [src: ADR-0014] [src: ADR-0016] [src: road.py:24]. No trial wording, no monthly price.
- **CTA:** "Set up your race at xctimer.com/host" with UTM tags (see UTM Links). Ad button: Sign Up or Learn More.
- **Pillars (from positioning.md):** (1) Time your own event, (2) Build it free, go live when ready, (3) Everything in one place with live results.
- **Creative:** UI screenshots and screen recordings only, from a test event built with made-up adult names. Nothing exists in the repo as ready-made image files, so Rob captures them **[Rob-only]**.
- **Launch blockers outside this doc:** WP-0008 (first-event-only promo flag) must be deployed and Rob must create FIRSTRACE in /organizers before any post names the code [src: ADR-0016]. The privacy page promises no third-party tracking, so UTMs are the only measurement until Rob decides on a Pixel [src: docs/marketing/positioning.md].

## Checklist before posting anything

- [ ] **[Rob-only]** WP-0008 deployed; FIRSTRACE created in /organizers (100% off, first event only, max uses blank) [src: ADR-0016].
- [ ] **[Rob-only]** Capture the screens listed in Creative Briefs from a test event with made-up adult names.
- [ ] **[Rob-only]** Confirm /host keeps working with the UTM query string (positioning.md notes /host does not capture UTMs; they appear only in web analytics or referrer).
- [ ] **[Rob-only]** Review each post and approve it yourself. Reply to comments within 1 business day [src: docs/marketing/fb-playbook.md].
- [ ] Never claim: waivers for fun runs, card payment of runner entry fees, a long-term results archive (events are deleted 30 days after the date), chip-level accuracy, or compliance badges [src: docs/marketing/positioning.md].

## Ad Variants

**For later paid phase.** None of these run while ad spend is zero [src: ADR-0007]. Limits: primary text up to 125 characters, headline up to 40. The "Inv" column points to the positioning.md Feature Inventory rows that back the claims. `scripts/marketing/check_ads.py` re-counts every limit.

### V1: Pillar 1, "Skip the timing company"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Skip the timing company. Time your own 5K or fun run with phones and a finish-line camera.` | 90 | Inv 12, 13 |
| Headline | `Time your own fun run` | 21 | Inv 12 |
| Description | `Phone timing, bibs and live results.` | 0 | Inv 11, 12, 14 |
| CTA button | `Learn More` | - | Link: xctimer.com/host |

### V2: Pillar 1, "Helpers join by QR"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Your volunteers scan a QR code and start timing. No logins, no training session needed.` | 87 | Inv 12 |
| Headline | `Helpers join with a QR code` | 27 | Inv 12 |
| Description | `Tap each finisher, then attach bib names.` | 0 | Inv 12 |
| CTA button | `Learn More` | - | Link: xctimer.com/host |

### V3: Pillar 2, "Build it free"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Build your race page, races and age groups free. Open registration only when you are ready.` | 91 | Inv 2, 7 |
| Headline | `Build your race free` | 20 | Inv 2 |
| Description | `Registration stays closed until you go live.` | 0 | Inv 2 |
| CTA button | `Sign Up` | - | Link: xctimer.com/host |

### V4: Pillar 2, "First race free"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Your first race is free with code FIRSTRACE, then $50 per event. Set up yours at xctimer.com/host.` | 98 | Inv 2, 4 [src: ADR-0014] [src: ADR-0016] [src: road.py:24] |
| Headline | `First race free: FIRSTRACE` | 26 | Inv 4 [src: ADR-0016] |
| Description | `Flat fee per event, not per runner.` | 0 | Inv 2 [src: road.py:24] |
| CTA button | `Sign Up` | - | Link: xctimer.com/host |

### V5: Pillar 3, "One place"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Sign-ups, printed bibs, timing and live age-group results in one place. Plan your spring fun run.` | 97 | Inv 6, 11, 12, 14 |
| Headline | `Sign-ups to results, one place` | 30 | Inv 6, 14 |
| Description | `Public sign-up page with link and QR.` | 0 | Inv 6 |
| CTA button | `Learn More` | - | Link: xctimer.com/host |

### V6: Pillar 3, "Results everyone can follow"

| Field | Copy | Chars | Basis |
|---|---|---|---|
| Primary text | `Share one live results link or QR with runners and families. Add a course map with water stations.` | 98 | Inv 14, 15 |
| Headline | `Live results for everyone` | 25 | Inv 14 |
| Description | `Results by gender and age group.` | 0 | Inv 14 |
| CTA button | `Sign Up` | - | Link: xctimer.com/host |

Copy notes: V6 course map applies to road events [src: coursemap.py:127]. No variant promises results beyond 30 days after the event [src: reap.py].

## Creative Briefs

Rules for every brief: real product screens only (screenshots or screen recordings of xctimer.com), no stock people, no photos of identifiable people, and especially no minors or runner names. Use a test event Rob builds with made-up adult names (for example "Pat Sample"). `demo_seed.py` seeds school-district demo data only, so use it only for a school screen, never in a fun-run asset [src: demo_seed.py]. Sizes: 1:1 and 4:5 for the feed, 9:16 for Reels/Stories, keep text in the center 80%.

| Variant | Format | Real screen to capture | On-screen text | Notes |
|---|---|---|---|---|
| V1 | 15 s video, 9:16 | Phone timing page: tap-to-record finishers, then bib attach [src: phone.py] [src: road.py:1482] | "Time your own fun run" then "xctimer.com/host" | Show the screen only, no hands or faces. Add captions; most viewers watch muted. |
| V2 | 12 s video or 3-frame carousel | The no-login helper QR and the phone timing page it opens [src: phone.py] [src: road.py:1482] | "Scan. Tap. Done." | Blur or fake the QR target if it contains a real event token. |
| V3 | 1:1 static, or 20 s screen recording | /host start form (event name, date, email), then the races/age-groups setup [src: https://xctimer.com/host] [src: road.py:1470] | "Build it free. Go live when you're ready." | Use made-up event name and email. |
| V4 | 1:1 static | /host page showing the pricing line, with a text banner for the code [src: https://xctimer.com/host] | "First race free with code FIRSTRACE" | Banner text is design, the screen behind it is real. Do not add any other price. |
| V5 | 4:5 carousel, 4 cards | Public registration page, bib sticker sheet preview, phone timing, live results [src: road.py:849] [src: road.py:733] [src: road.py:1486] | One short label per card | Bib sheet should show made-up bib numbers only. |
| V6 | 15 s video, 9:16 | Live results page filtered by age group, then the course map with water stations [src: road.py:1486] [src: coursemap.py:127] | "One link for runners and families" | Use made-up adult names; if the map shows a real location, pick a public park and get Rob's OK. |

Capture checklist **[Rob-only]**:

- [ ] Build one test event on xctimer.com with fake adult names; add two races (5K and Fun Run).
- [ ] Record /host, registration page, phone timing, bib sheet and live results; export clean PNGs and one MP4 each.
- [ ] Check every frame for real names, emails, tokens or any child's name or image; re-record if found.

## Organic Calendar

Four weeks, 3 posts per week, Page-first, reuse on Instagram where noted. Weeks start Monday. Week 4 is the holiday week, so posts stay light. Schools appear in 2 of 12 posts (marked S). Post times are a suggestion; adjust to when Rob's groups are active.

### UTM Links

Convention from the playbook: lowercase, hyphenated [src: docs/marketing/fb-playbook.md]. Base link:

`https://xctimer.com/host?utm_source=facebook&utm_medium=organic-social&utm_campaign=funrun-organic-202612&utm_content={post-id}`

For group posts use `utm_source=fb-group` and `utm_medium=group-post`. Replace `{post-id}` with the id in the table (for example `w1-pin`).

### Weeks and posts

| ID | Date | Pillar | Format | Copy | Media |
|---|---|---|---|---|---|
| w1-pin | Tue 2026-12-01 | 1 | Pinned text + link | "We built XCTimer so a volunteer can time their own fun run. Phones and a finish-line camera do the timing, helpers join by QR, and runners get a live results link. Planning a spring race? Set up yours at xctimer.com/host" + UTM link | V1 video (Inv 12, 13, 14) |
| w1-tip | Thu 2026-12-03 | none (value) | Text + checklist image | "Spring fun run checklist, 12 weeks out: pick a date, check the route and permit, line up volunteers, decide how runners register, plan who handles timing and results. Save this for your planning meeting. What would you add?" | Plain checklist graphic, no product screens |
| w1-demo | Sat 2026-12-05 | 2 | 20 s video | "Starting a race page takes a few minutes: event name, date, your email. Building it is free; you pay only when you open registration. xctimer.com/host" + UTM link | V3 recording (Inv 1, 2) |
| w2-how | Tue 2026-12-08 | 1 | Text + video | "How do you time a fun run without a timing company? One way: a volunteer taps each finisher on a phone, then attaches names by scanning or typing the bib. Here is what it looks like." + UTM link | V1 video (Inv 12) |
| w2-offer | Thu 2026-12-10 | 2 | Image | "Your first race is free with code FIRSTRACE, then $50 per event. Build your race page first and use the code when you open registration. xctimer.com/host" + UTM link | V4 static (Inv 2, 4) [src: ADR-0016] [src: road.py:24] |
| w2-S1 (S) | Sat 2026-12-12 | 1 | Text | "Fun run organizers: the same phone timing also runs school cross country and track meets, so a team or PTA can reuse what it learns. Planning a community 5K this spring? xctimer.com/host" + UTM link | V1 video (Inv 12; schools secondary per positioning.md) |
| w3-bibs | Tue 2026-12-15 | 3 | Image | "Bibs without the headache: print weatherproof bib stickers with your event logo, and the finish-line camera can read the tags. Your volunteers match names to bibs by scanning or typing the number." + UTM link | Bib sheet preview (Inv 9, 11, 13) |
| w3-results | Thu 2026-12-17 | 3 | Video | "Runners and families always ask: where are the results? Share one live results link or QR, with results by gender and age group. Download your results after the event; events are removed 30 days after the date." + UTM link | V6 video (Inv 14, 17) |
| w3-map | Sat 2026-12-19 | 3 | Image | "Where are the water stations? Put them on a satellite course map and share it before race day. A fly-over helps spectators and first-timers picture the route." + UTM link | Course map screen (Inv 15) |
| w4-ask | Tue 2026-12-22 | none (engage) | Text, no link | "Organizers: what is the hardest part of putting on a fun run? Registration, volunteers, bibs, results, something else? We'll turn the top answers into guides in January." | No media |
| w4-S2 (S) | Thu 2026-12-24 | 1 | Short text | "Happy holidays from XCTimer. If you run school cross country or track meets, the same phone timing and live results work for meets too. Rest up; spring will be here soon." | Simple greeting card, no people |
| w4-cta | Sat 2026-12-26 | 2 | Image | "Planning over the break? Build your race page free at xctimer.com/host. Your first race is free with code FIRSTRACE, then $50 per event." + UTM link | V3 or V4 static [src: ADR-0016] [src: road.py:24] |

Calendar notes:

- Dates 12-24 and 12-26 are holiday-adjacent; Rob may shift or drop them. Keep 3 per week, and keep schools at 2 or fewer.
- Instagram (optional): reuse the video and image posts (w1-demo, w2-how, w3-bibs, w3-results, w4-cta); Instagram captions do not carry clickable links, so say "link in bio" and set the bio link with UTMs **[Rob-only]**.
- Follow the January plan: Dec–Feb is when organizers plan Mar–Jun events [src: ADR-0013]. After week 4, repeat the pillars and use real feedback from the w4-ask thread.
- Testimonials: none exist; do not post any until Rob has real, permissioned ones.

### Facebook Groups Outreach Plan

Goal: be useful in local running and PTA groups, and mention XCTimer only where the rules allow it. No spam [src: docs/marketing/fb-playbook.md] [src: https://transparency.meta.com/policies/community-standards/spam/].

| Step | Action | Who |
|---|---|---|
| 1. List | Find 10 to 15 groups: local running clubs, 5K/race organizer groups, PTA/PTO/booster groups, church and charity event groups. Adults-only groups, no groups for kids. | **[Rob-only]** (needs Rob's profile) |
| 2. Read rules | Record each group's rule on promotion and links in a sheet; skip groups that ban it. | **[Rob-only]** |
| 3. Lurk and help (weeks 1-2) | 2 to 3 helpful replies per week, no links, answer questions on timing, bibs, registration, permits. | **[Rob-only]** |
| 4. Ask admin (week 2+) | Message the admin using the template below before posting any link. | **[Rob-only]** |
| 5. One post (week 3+) | Where allowed, one post per group, with a different opening for each group. Link carries `utm_source=fb-group`. | **[Rob-only]** |
| 6. Log | Record posts, replies, clicks and any signups in the weekly review [src: docs/marketing/fb-playbook.md]. | **[Rob-only]** |

Rules: disclose "I work on XCTimer" every time; at most 1 promo post per month per group; never paste the same text in many groups; never tag people who did not ask; never use fake accounts or fake testimonials; accept a "no" without argument.

Admin message template: "Hi, I'm Rob. I built XCTimer, a tool that lets volunteer organizers time their own fun runs with phones. I'd like to share a short how-to for members who are planning spring races. Is that OK with your rules, and where would you want it posted?"

Group reply template (no link): "For a small fun run, a volunteer can tap finishers on a phone and attach bib numbers afterward; practice with a few friends before race day. Happy to share how we did it if useful. Disclosure: I work on XCTimer."

Group post template (only where allowed): "Disclosure: I build XCTimer. If you're planning a spring fun run, here is a short walkthrough of timing it yourself with phones and sharing live results. Your first race is free with code FIRSTRACE, then $50 per event. Questions welcome." + UTM link [src: ADR-0016] [src: road.py:24]

## Test Matrix

Today (no spend) the test is organic: which angle gets replies and clicks from which audience. The paid half is for later paid phase.

### Audiences

| Id | Audience (persona from positioning.md) | Where organic | Paid interest ideas (verify names in Ads Manager) |
|---|---|---|---|
| A1 | P1: PTA/booster fundraiser leads | PTA/PTO/booster groups | Fundraising, parent-teacher organizations; adults 25+ only |
| A2 | P2: Church or charity run organizers | Church and charity event groups | Charity events, nonprofit organizations; adults 25+ only |
| A3 | P3: Running-club race leads | Local running club groups | Running, 5K events; adults 25+ only |
| A4 | P4: Small race directors | Race director groups | Race directing, timing; adults 25+ only |

All audiences are adults. Never use interests, lookalikes or lists that target children or teens. Age 18+ is the minimum; 25+ is a house choice to be reviewed after the first data.

### Variant versus audience

| Variant | A1 PTA | A2 Church/charity | A3 Running club | A4 Small race director | Organic equivalent |
|---|---|---|---|---|---|
| V1 Skip the timing company | Test | Test | **Lead** | **Lead** | w1-pin, w2-how |
| V2 Helpers join by QR | **Lead** | **Lead** | Test | Hold | w2-how |
| V3 Build it free | **Lead** | Test | Hold | Test | w1-demo, w4-cta |
| V4 First race free | Test | **Lead** | Test | Test | w2-offer, w4-cta |
| V5 One place | Hold | Test | Test | **Lead** | w3-bibs |
| V6 Results for everyone | Test | Test | **Lead** | Hold | w3-results, w3-map |

Lead = run first in that audience; Test = second round; Hold = skip until data. These assignments are hypotheses, not findings [src: docs/marketing/positioning.md].

### Rules for the test

- One variable at a time: same audience, different variant; or same variant, different audience.
- Organic read: comments, shares, saves, link clicks by `utm_content`. Compare posts after 7 days.
- Paid read (later): hook rate, link CTR and cost per host signup, but only after spend is approved. Targets are PROVISIONAL(Q-0002).
- Primary conversion (manual until tracking exists): host signups and published events, counting FIRSTRACE redemptions [src: ADR-0016].
- Stop and tell Rob if any ad is rejected or any post draws a policy notice.

## Sources

Claims: `docs/marketing/positioning.md` Feature Inventory; ADR-0007, ADR-0013, ADR-0014, ADR-0016; road.py, phone.py, coursemap.py, reap.py, demo_seed.py. Playbook and UTM convention: `docs/marketing/fb-playbook.md`. Group conduct: https://transparency.meta.com/policies/community-standards/spam/
