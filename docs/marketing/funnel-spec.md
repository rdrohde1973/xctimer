# XCTimer Fun-Run Funnel Spec (Landing Page, Host Signup, Tracking)

> Plan for Rob and the developer; nothing has been built, published or spent. Focus: fun-run organizers (ADR-0013), organic-only at zero spend (ADR-0007). Sources: `file:line` = this repo, read at the route/function level for the /host flow in `road.py`, `auth.py` and `app.py`. Offer: first event free with code FIRSTRACE [src: ADR-0016], then $50 per event PROVISIONAL(Q-0007).

## Summary

- **The flow already works end to end.** /host form, emailed magic link, event build, then go live by Square card payment or promo code. [src: road.py:1093] [src: road.py:1143] [src: road.py:1200] [src: road.py:1306]
- **Landing URL decision (judgment call):** until a dedicated page is built, the Page CTA and every post link to `https://xctimer.com/host` plus UTM tags (see Tracking Events). /host already is a one-CTA page with a form. A purpose-built `/fun-run` page is a later WP (Gap 1), not a launch blocker.
- **Offer:** "Your first race is free with code FIRSTRACE, then $50 per event." FIRSTRACE is final [src: ADR-0016]. The $50 fee is the default [src: road.py:24]; the offer wording stays PROVISIONAL(Q-0007) in the sense that the per-event price is Rob's to change.
- **Launch dependency:** FIRSTRACE must be a first-event-only code. That flag is being added by WP-0008 (in progress). Do not post the code before it is deployed and created (see Rob-only launch steps).
- **Biggest friction:** the promo box is hidden on the event page after signup, so a host has to find it. Biggest tracking gaps: no UTM capture, no Pixel/CAPI, and the privacy page promises no third-party tracking scripts. [src: road.py:1414] [src: app.py:820]
- **Meta events:** `Lead` at /host email submit, `CompleteRegistration` at magic-link verify, custom `PublishEvent` at go-live (not `Purchase`, because the first event is free). `Purchase` fires additionally only when real money is paid.
- **Rob decisions:** approve a Pixel (and the privacy wording change), approve the candidate code WPs below, and run the launch checklist.

## Landing Page

**Purpose:** one job, get a fun-run organizer to click "Create my event" on /host. One CTA. Schools get a single secondary line at the bottom.

### Wireframe (mobile first)

```
+----------------------------------------------+
| XCTimer                                      |
+----------------------------------------------+
| HERO                                         |
|  H1: Time your own fun run.                  |
|  Sub: Sign-up page, bibs, phone timing and   |
|       live results in one place.             |
|  [ Create my event -> ]   <- the one CTA     |
|  small: Build it free. First race free with  |
|         code FIRSTRACE.                      |
+----------------------------------------------+
| PROOF STRIP (3 icons, features only)         |
|  Public sign-up page | Printed bibs | Live   |
|  results                                     |
+----------------------------------------------+
| HOW IT WORKS (3 steps)                       |
|  1 Name your event, enter your email         |
|  2 Build it: races, age groups, sign-up page |
|  3 Go live with FIRSTRACE, open registration |
+----------------------------------------------+
| WHAT YOU GET (bullets, section below)        |
+----------------------------------------------+
| PRICE BOX                                    |
|  First event free with FIRSTRACE.            |
|  Then $50 per event PROVISIONAL(Q-0007).     |
|  [ Create my event -> ]  (same CTA, repeat)  |
+----------------------------------------------+
| FAQ (4 items)                                |
+----------------------------------------------+
| Footer: schools line, Privacy, Contact       |
+----------------------------------------------+
```

### Copy (all claims cited; use as written)

| Block | Copy | Source for the claim |
|---|---|---|
| H1 | Time your own fun run. | [src: road.py:1097] |
| Sub | A public sign-up page, printed bibs, phone or camera timing, and live results the whole crowd can follow. | [src: road.py:1097] |
| CTA button | Create my event | [src: road.py:1107] |
| Under CTA | Build it free. Your first race is free with code FIRSTRACE. | [src: ADR-0016] |
| Step 1 | Name your event and give us your email. We send you a private link. | [src: road.py:1103] |
| Step 2 | Build your races and age groups, and get a public sign-up page with a link and QR. | [src: road.py:849] [src: road.py:1470] |
| Step 3 | Go live with FIRSTRACE and open registration. | [src: road.py:1306] |
| Bullet: bibs | Printed bib stickers with camera-readable tags and your event logo. | [src: road.py:733] |
| Bullet: timing | Time it with a phone: one helper taps each finisher, then scans or types the bib. | [src: phone.py] [src: road.py:1482] |
| Bullet: results | Live results by gender and age group, with a share link. | [src: road.py:1486] |
| Bullet: course | A course map with water stations for road events. | [src: coursemap.py:127] |
| Bullet: help | A built-in setup assistant walks first-timers through it. | [src: road.py:1492] |
| Price box | First event free with FIRSTRACE. After that, $50 per event. PROVISIONAL(Q-0007) | [src: ADR-0016] [src: road.py:24] |
| FAQ: what happens to my event after? | Your event and its owner login are removed 30 days after the event date, so download your results first. | [src: reap.py] |
| FAQ: can runners pay online? | Entry fees, if you charge any, go through your Venmo or at packet pickup, not by card. | [src: road.py:866] |
| FAQ: do I need an account? | No password. You sign in from the private link in your email. Runners need no account. | [src: road.py:1222] [src: road.py:849] |
| FAQ: how do I get my link again? | Use "Email my link" on the page. | [src: road.py:1109] |
| Schools line (footer, one line) | Coaching a school team? XCTimer also runs cross-country and track meets. | [src: xc.py] [src: track.py] |

**Do not claim:** waivers for fun runs, card payment for runners, long-term result archives, chip-mat accuracy, or any compliance certification. [src: docs/marketing/positioning.md]

## Host Signup Flow

### Current steps (audited)

| # | Step | What happens | Source |
|---|---|---|---|
| 1 | Land on /host | Form: event name, date, your name, email. Also an "Email my link" form for returning hosts. | [src: road.py:1093] |
| 2 | POST /host | Validates name and email. If the email already belongs to a web host, resend the link; if it belongs to any other login, show "already registered" (400). Otherwise create user, a draft event with one race "5K", a 60-day token, and email the link. | [src: road.py:1143] |
| 3 | "Check your email" | Static confirmation page. | [src: road.py:1186] |
| 4 | Open magic link /host/go/token | Validates token and expiry, records last login, creates a 60-day event-owner session, redirects to the event page. | [src: road.py:1200] |
| 5 | Build the event | Setup tab: races, age groups, logo, registration text, fee, Venmo. Registration cannot be opened until paid. | [src: road.py:719] |
| 6 | Go live | Banner offers Square card payment or a promo box. 100% code publishes at once; partial code goes to Square for the reduced amount. | [src: road.py:1379] [src: road.py:1306] |
| 7 | Open registration | Host ticks "reg open" in settings after publishing. | [src: road.py:721] |
| 8 | Race day, results, auto-delete | Timing and live results; event removed 30 days after its date. | [src: reap.py] |

### Friction points and fixes

| # | Friction | Fix | Needs code? |
|---|---|---|---|
| F1 | /host has no mention of FIRSTRACE, so the offer is invisible at signup. | Add one line under the form: "First race free with code FIRSTRACE." | Yes, Gap 1 |
| F2 | The check-your-email page does not say where the email comes from or to check spam. | Add: "From XCTimer. Check spam if it does not arrive in a few minutes. Wrong address? Go back." | Yes, Gap 2 |
| F3 | Email is the only path in; a typo loses the host with no recovery signal. | Add a confirm-email hint and a visible "Email my link" retry on the confirmation page. | Yes, Gap 2 |
| F4 | A host whose email already has a coach or admin login gets a dead end (400). | Keep the guard but add a plain-language alternative ("use a different email or contact admin@xctimer.com"). | Yes, Gap 2 |
| F5 | The promo box sits inside the go-live banner and is easy to miss; the code is typed by hand. | Support a `?code=FIRSTRACE` prefill from the landing URL, stored with the event, and pre-fill the box. | Yes, Gap 3 |
| F6 | Event date is required but not explained; the event is deleted 30 days after it. | Helper text under the date: "Your event is removed 30 days after this date. Download results first." | Yes, Gap 2 |
| F7 | After publishing, registration still has to be opened by hand. | Show a "Next: open registration" step with a direct link right after publish. | Yes, Gap 2 |
| F8 | Default race is named "5K" regardless of what the host planned. | Mention in nudge emails that races can be renamed or added; no code needed. | No |
| F9 | A partial-discount code is consumed when checkout starts, even if the host abandons checkout. | Not relevant to FIRSTRACE (a full-discount code) [src: road.py:1306]. Note only; do not use partial codes in the campaign. | Optional, later |
| F10 | No signup source recorded, so Facebook-sourced hosts cannot be told apart. | UTM capture (Gap 1). | Yes |

## Onboarding Nudges

Emails go through the existing email sender (Resend, SMTP fallback). [src: auth.py:454] Today only the magic-link email exists. [src: road.py:1115] All nudges need a scheduled job (Gap 4). Each is short, plain text, with one link, and an unsubscribe line. Send them to hosts only, never to registered runners.

| # | Trigger | Timing | Subject | Core message (one idea) | Link |
|---|---|---|---|---|---|
| E0 | Host signup (exists) | Immediate | Your XCTimer event link | Private link; keep it private. | /host/go/token |
| E1 | Signup, event not yet built (no extra races/settings changed) | 1 day after signup | Build your event in 10 minutes | Add your races and age groups; the assistant can help. | Magic link |
| E2 | Built, not published | 3 days after signup | Ready to go live? Your first race is free | Enter FIRSTRACE in the Go live box. | Event page |
| E3 | Published, registration closed | 1 day after publish | Open registration | Tick "registration open" and share the sign-up link and QR. | Event page |
| E4 | Published, 14 days before race date | Date based | Two weeks out: order your bibs | Print bibs and test the sign-up page yourself. | Event page |
| E5 | 3 days before race date | Date based | Race-day timing checklist | Charge phones, pick two helpers, test one tap-then-scan run. | Event page |
| E6 | Race date | Morning | Race day: your timing cheat sheet | One helper taps each finisher; a second scans or types bibs; results go live. | Event page |
| E7 | 1 day after race date | Date based | Your results are ready | Share the results link; download them, since the event is removed 30 days after the race date. | Results link |
| E8 | 20 days after race date | Date based | Planning another race? | Second event is $50 PROVISIONAL(Q-0007). Start from your same email. | /host |

Rules: stop the sequence once the stage is passed (never email E2 to a published host); one nudge per day maximum; claims limited to those in the Landing Page copy table. Race-day tips are procedure only, with no accuracy claims. [src: phone.py]

## Offer & Upgrade Path

| Stage | What the host sees | Mechanism | Source |
|---|---|---|---|
| First event | "First race free with code FIRSTRACE" | 100% promo publishes with no payment; WP-0008 limits it to a host's first event | [src: ADR-0016] [src: road.py:1321] |
| Second and later events | $50 per event, pay by Square card | Existing go-live payment | [src: road.py:24] [src: road.py:1268] |
| Venmo path | Honor-system publish button exists in code | Not promoted in copy (unverified payment) | [src: road.py:1234] |
| Partial discounts | Not used in the campaign | Would route to Square | [src: road.py:1330] |

**Repeat-organizer path:** the account and its event are deleted 30 days after the event date [src: reap.py], so a repeat organizer starts again at /host with the same email (no leftover account to collide with). Nudge E8 covers this. Open question for Rob: should a repeat host get a loyalty code (for example a partial discount)? Not needed for launch; note only.

**Not in this offer:** the 30-day trial and monthly pricing do not apply to fun runs. [src: ADR-0014]

### Rob-only launch steps

- [ ] **[Rob-only]** Wait until WP-0008 (first-event-only flag on promo codes) is merged and deployed.
- [ ] **[Rob-only]** In /organizers, create code FIRSTRACE: 100% off, first event only, max uses left blank. [src: ADR-0016] [src: road.py:178]
- [ ] **[Rob-only]** Test it yourself with a throwaway email: sign up, publish with FIRSTRACE, then try FIRSTRACE on a second event from the same email and confirm it is rejected.
- [ ] **[Rob-only]** Set the Page CTA to Sign Up pointing at the landing URL with UTM tags (see below).
- [ ] **[Rob-only]** Only then post the code publicly.

## Tracking Events

### Funnel to Meta event map

| Step | Route or trigger | Meta event | Pixel / CAPI | Parameters (no sensitive data) |
|---|---|---|---|---|
| Visit | GET /host (or /fun-run) | `PageView` | Pixel | none |
| Email submitted | POST /host, success branch ("Check your email" page) | `Lead` | Pixel on confirmation page plus CAPI | `event_id`, hashed email only with consent; `content_name`=fun_run_host |
| Magic link verified | GET /host/go/token, after session created | `CompleteRegistration` | CAPI (server redirect has no page to carry a Pixel) with Pixel on the event page `?welcome=1` | `event_id`, `status`=true |
| Event published free | POST /meets/id/host-redeem returning paid, or landing on `/meets/id?paid=1` | custom `PublishEvent` | CAPI plus Pixel on the `?paid=1` page | `event_id`, `promo`=FIRSTRACE |
| Event published paid | GET /meets/id/host-square-return, or the Square webhook marking paid | `Purchase` plus custom `PublishEvent` | CAPI | `value`=amount actually charged, `currency`=USD |
| Registration opened (optional) | POST settings save with reg open set | custom `OpenRegistration` | CAPI | `event_id` |

Notes:
- A free publish is not a `Purchase`; do not send a value of zero as a purchase. Use the custom `PublishEvent`. Standard names are case-sensitive; custom names are allowed only where no standard event fits. [src: https://www.facebook.com/business/help/2254103654917599]
- The Square webhook can publish an event when the buyer never returns [src: road.py:1358], so the paid event must fire from the server (CAPI), not only from the browser page.
- De-duplicate with a shared `event_id` across Pixel and CAPI. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events]
- Fire `Lead` on form success, not on button click. Do not send event dates, event names or anything tied to minors; the funnel concerns adult organizers only. [src: ADR-0013]
- Consent: the privacy page says there are no third-party tracking scripts [src: app.py:820]. That text must be changed before a Pixel loads (Rob decision), and the Content-Security-Policy must allow Meta's script and image hosts. [src: app.py:994]

### UTM capture and storage

| Item | Spec |
|---|---|
| Standard tags on every Facebook/Instagram link | `utm_source` (facebook or instagram), `utm_medium` (social), `utm_campaign` (firstrace), `utm_content` (post or ad name) |
| Page CTA URL | `https://xctimer.com/host?utm_source=facebook&utm_medium=social&utm_campaign=firstrace&utm_content=page_cta` |
| Capture | On GET /host, read the four UTM params and a `fbclid` if present; keep them in the form as hidden fields and a short first-party cookie so they survive a reload |
| Storage | On POST /host, save them into the new event's settings (the existing `settings_json` on the meet) as `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `fbclid` — no schema change needed |
| Use | Read back at magic-link verify and at publish, so every later event is attributed to the original source |
| Privacy | Store only these tags and the click ID; they are removed with the event 30 days after its date [src: reap.py] |

## Implementation Gaps

Candidate code WPs, for Rob to approve. WP-0008 (first-event-only flag on promo codes) is in progress and is not listed. This WP edits no code. `road.py` and `db.py` are named below only as files a future WP would touch.

| # | Candidate WP | What it does | Files it would touch |
|---|---|---|---|
| G1 | /host landing copy and UTM capture | FIRSTRACE line, hero copy and FAQ on /host; read UTM params; hidden fields; store in `settings_json` on create. Optional later `/fun-run` page that reuses it. | `road.py` (host_start, host_create), `app.py` (route for /fun-run, landing link), `ui.py` (shared styles) |
| G2 | Host-flow friction fixes | Items F2, F3, F4, F6, F7: better confirmation page, hints, next-step prompt after publish. | `road.py` (host_create, host_banner), `ui.py` |
| G3 | Promo prefill | `?code=FIRSTRACE` prefill carried from landing to the go-live box. | `road.py` (host_banner, host_go) |
| G4 | Onboarding nudge emails | Scheduled job sending E1 to E8, stop rules, unsubscribe line, a sent-log to avoid repeats. | new `nudges.py`, `db.py` (sent-log table or settings flags), `auth.py` (send_email reuse), systemd timer like `reap.py` [src: reap.py] |
| G5 | Meta Pixel and Conversions API | Pixel snippet on the /host pages and event page; CAPI sender called at the points in the event map; consent and privacy wording; CSP update. | `ui.py` (head snippet, `_host_page`), `app.py` (CSP at app.py:994, privacy text at app.py:820), `road.py` (fire points), new `meta_capi.py` |
| G6 | Funnel stage reporting | Admin view counting hosts per stage and source: signed up, verified, published, registration opened. | `admin.py`, `road.py` (stage flags in settings), `db.py` (only if a table is wanted) |

**Secrets:** the Pixel ID is not a secret, but the CAPI access token is. Both load from environment variables only (for example `META_PIXEL_ID`, `META_CAPI_TOKEN`), never in code, logs or git; add placeholders to `env.example`. If the variables are unset, the code sends nothing.

Priority for launch: G1 is small and enables attribution; the Page can launch with the UTM-tagged /host URL and an unmodified /host page, so nothing here blocks the first organic posts except the WP-0008 and FIRSTRACE steps above.

## Source Check

- Offer and code: [src: ADR-0016], [src: ADR-0014]; the price default is read from `HOST_FEE_CENTS` [src: road.py:24]. Per-event price after the first event stays PROVISIONAL(Q-0007).
- Everything in the Host Signup Flow table was read in `road.py` (lines 1037 to 1470); Square internals were not re-read.
- Not verified live: no request was made to xctimer.com in this WP; copy for /host is quoted from the code. [src: road.py:1093]
- Meta event names checked against the playbook's Tracking Plan. [src: docs/marketing/fb-playbook.md]
