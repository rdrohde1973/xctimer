# XCTimer Positioning, Personas & Messaging

> Product confirmed as XCTimer by ADR-0006 (Q-0001). Start is organic-only at $0 ad spend (ADR-0007). Free 30-day trial then a monthly plan, price unset (ADR-0008, PROVISIONAL(Q-0005)). This is a plan for Rob; nothing here has been published. Claim sources: `file` = this repo (worktree root), URL = live site fetched 2026-11-05.

## Summary

- **What XCTimer is:** a phone-based meet manager for junior high/middle school cross country and track: rosters, bibs, timing, scoring, live results, plus a self-serve fun-run host flow. [src: https://xctimer.com]
- **Who we market to:** (1) XC/track coaches and meet hosts, (2) athletic directors, (3) district administrators, (4) community fun-run organizers. Adults only; never minors. [src: docs/architecture-decisions/ADR-0006-campaign-product-is-xctimer-audience-is-.md]
- **Biggest finding:** a free-trial campaign has nothing to send people to. Coaches cannot sign up; accounts are created by an admin/invite. The only self-serve path is the fun-run host flow. [src: admin.py:619] [src: road.py:1093]
- **Today's only payment:** a one-time $50 per fun-run event via Square. No subscription, no trial, no pricing page. [src: square.py] [src: https://xctimer.com/host]
- **Timing:** it is November 2026, so XC is ending. The best window is a spring-track push (Jan–May) and a pre-season push for next fall.
- **Recommended angle:** "Run your whole meet from a phone: no timing company, no big invoice." The strongest differentiators are free-trial simplicity, district-wide shared rosters, and live results. Verify before using: competitors such as RaceTab and Athletic.net already have free tiers.
- **Open items for Rob:** plan price PROVISIONAL(Q-0005); what the trial includes PROVISIONAL(Q-0003); whether a tracking pixel is acceptable given the site's "no third-party tracking" promise (see Signup Funnel Today).

## Feature Inventory

Every row was checked against the live site and code. "Site" = marketed on xctimer.com; "Code" = implemented in this repo.

| # | Feature | Who it helps | Source |
|---|---|---|---|
| 1 | Cross-country timing console: tap-to-finish, DQ, reorder, combined results by gender | Coach, host | [src: xc.py] |
| 2 | MileSplit-style XC team scoring; Excel export of results | Coach, AD | [src: xc.py] [src: https://xctimer.com] |
| 3 | Public results page with QR link, live clock and finishers appearing as timed | Parents, spectators | [src: xc.py:2645] [src: https://xctimer.com] |
| 4 | Phone timing app; helpers join with a no-login QR code | Coach, volunteers | [src: phone.py] [src: meets.py] |
| 5 | Track and field engine: events by grade and gender, individual and relay entries, seeded or random heat/lane draws, points scoring, team totals | Coach, host | [src: track.py] |
| 6 | Field events: Long Jump, Shot Put with attempts; High Jump make/miss grid | Coach | [src: track.py:177] [src: https://xctimer.com] |
| 7 | Printed heat sheets, marked up at the meet; AI vision reads a photo of the marked sheet back in | Coach | [src: track.py] [src: https://xctimer.com] |
| 8 | AI roster intake: spreadsheet, CSV, PDF or Word becomes a clean roster with bibs; Google Sheet sync | Coach, AD | [src: schools.py] [src: ai.py] |
| 9 | Bib sticker PDFs (Avery) with QR; bib lists; bib check by scan or typing | Coach, host | [src: schools.py] [src: pdfs.py] |
| 10 | Robot-vision camera reads bibs at the finish from a phone (ArUco marker decoding) | Host | [src: https://xctimer.com] [src: aruco.js] |
| 11 | Course maps traced on satellite imagery; spectator 3D fly-over with mile marks | Host, spectators | [src: coursemap.py] [src: https://xctimer.com] |
| 12 | Race-morning email to coaches with heat times, bib list, results link and map/directions; works for coaches who never logged in | Visiting coach | [src: raceday.py] |
| 13 | Districts: multi-tenant, data isolated per district, role-based access (super admin, district admin, coach, timer) | District admin | [src: tenancy.py] [src: https://xctimer.com/security] |
| 14 | Athlete progress cards, PRs across XC and track | Coach, athlete | [src: insights.py] |
| 15 | AI Roster Insights chatbot, school-scoped or district-wide (for example, "what's the district record for the 100m?") | Coach, AD, district | [src: insights.py:349] [src: insights.py:518] |
| 16 | Championship picks: ranks the fastest runners per school by grade and gender, adjusting for course difficulty, with explainable close calls | Coach, district | [src: champ.py] |
| 17 | Parent e-sign waivers: district templates, tokenized no-login link, signature, timestamp and audit certificate PDF. Medical forms are NOT included | District admin, coach | [src: waivers.py] |
| 18 | Fun-run/community-race host flow: public sign-up page and QR, event logo/colors, bibs, results by gender and age group, optional Venmo pay-at-registration | Fun-run organizer | [src: road.py:849] [src: road.py:866] [src: https://xctimer.com/host] |
| 19 | Self-serve event fee: one-time Square checkout; payment verified server-side before the event goes live; discount codes | Fun-run organizer | [src: square.py] [src: road.py:178] |
| 20 | Security page: no third-party ad/tracking scripts, nightly backups, US hosting, deletion on request, "designed with" FERPA/COPPA expectations (not a compliance claim) | AD, district | [src: https://xctimer.com/security] |

**Do-not-claim list:**
- No claim of FERPA/COPPA compliance or certification; the site says only that it designs with those expectations. [src: https://xctimer.com/security]
- No claim of medical forms or HIPAA features. [src: waivers.py]
- No claim of chip-mat accuracy parity; the site says phones replace chip mats, but no accuracy data exists in the repo.
- No claim of a self-serve coach trial, pricing page, or billing until those are built.
- Track High Jump: site copy says "make/miss grid" and code supports it, but a code comment at track.py:1252 says only best height is recorded in one flow. QA before using in ads. [src: track.py:1252]

## Signup Funnel Today

Path map as of 2026-11-05:

| Audience | Path today | Source |
|---|---|---|
| Coach / AD / district | No self-serve signup. A super admin or district admin creates the user, who gets a setup-email link. Public CTAs are "Sign in" and "Get in touch" / "Bring XCTimer to your district" (email). | [src: admin.py:619] [src: auth.py] [src: https://xctimer.com] |
| Fun-run organizer | `/host`: enter event name, date, name, email, get a private link by email, build free, pay a one-time fee to open registration. | [src: https://xctimer.com/host] [src: road.py:1093] |
| Helper / runner / spectator | No account needed (QR). | [src: https://xctimer.com] |

**Gaps that block a free-tier signup (each is a likely code WP):**

- [ ] **No coach self-serve signup.** Nothing for an ad to click that ends in an account. (Boss note, ADR-0006.)
- [ ] **No free trial exists in code.** The 30-day trial (ADR-0008) is only a decision; no trial state, expiry or reminder logic was found.
- [ ] **No subscription billing.** `square.py` is a one-time payment link, not a subscription; the docstring says it mirrors 321draw's boundary but is one-time. [src: square.py]
- [ ] **Only payment is the $50 fun-run fee.** One event, one time. [src: square.py] [src: road.py:24]
- [ ] **No pricing page.** The home page gives no price, tier or trial. [src: https://xctimer.com]
- [ ] **No tracking.** The security page promises no third-party advertising or tracking scripts. A Meta Pixel would contradict it unless the page is updated or a server-side-only approach is chosen. Rob decides. [src: https://xctimer.com/security]
- [ ] **No coach-facing landing page** with one message and one CTA; the home page serves four audiences at once.
- [ ] **Student-data trust.** District buyers will ask for a security questionnaire; the page invites them by email but states no retention schedule. [src: https://xctimer.com/security]
- [ ] **Plan name and price** PROVISIONAL(Q-0005); free-trial contents PROVISIONAL(Q-0003).

**Interim funnel that works today (organic, $0):** post → `/host` for fun-run organizers (real, self-serve) and "Get in touch" for coaches/districts (manual onboarding). The trial remains PROVISIONAL(Q-0003) until the signup is built.

## Seasonality

| Window | What matters | Marketing move |
|---|---|---|
| Aug–Nov (XC) | Season ending now (Nov 2026) | Organic only: recap and "how it went" content; collect interest from coaches who used it. Do not push trials now. |
| Nov–Dec | Coaches plan next season; off-season is when software is chosen | Pre-season planning content for track; district demos |
| Jan–May (track) | Meet schedules and entries start Jan | Main push: track meets, heat sheets, field events, live results |
| Spring/summer | Fun runs and 5Ks (organizers plan months ahead) | Fun-run host content; works today |
| Summer | Budget and purchasing for the next school year | AD and district outreach for fall XC |

Source for the XC and track windows: Boss brief, 2026-11-05. Budget timing for schools is an assumption to validate.

## Personas

Personas are hypotheses for ad targeting and messaging, not research. Validate against Rob's real users.

### 1. The Meet-Hosting Coach (primary)
- **Who:** junior high/middle school XC and track coach, often teaching full time, who hosts or attends dual and invitational meets.
- **Goals:** run meets without paying a timing company; get results to parents fast; get entries without spreadsheet chaos.
- **Frustrations:** messy rosters, paper heat sheets, hand-scored results, volunteers needing training.
- **Why XCTimer:** phone timing, no-login helper QR, AI roster import, instant public results. [src: phone.py] [src: schools.py]
- **Channels:** Facebook groups for coaches (join as an individual, follow group rules), Page posts, Reels of meet-day setup. No contact-list targeting.
- **Objection:** "Will it be accurate and will my athletes' data be safe?"

### 2. The Athletic Director
- **Who:** a school AD overseeing several sports with a small budget and staff.
- **Goals:** fewer vendors and invoices; compliant handling of student data; coaches who are not struggling on meet day.
- **Frustrations:** coaches each using a different tool; data-privacy questions.
- **Why XCTimer:** one tool for XC and track, waiver e-sign, role-based access. [src: waivers.py] [src: tenancy.py]
- **Objection:** "What does it cost, who sees student data, and does it integrate with what we use?" Price PROVISIONAL(Q-0005).

### 3. The District Administrator
- **Who:** district-level athletics or activities coordinator running multiple schools' meets.
- **Goals:** one roster, shared bibs, consistent results across meets, season points and records.
- **Frustrations:** each school entering the same athletes again; visiting coaches with different formats.
- **Why XCTimer:** shared roster across schools, bib pool, seeding from season bests, district record board. [src: https://xctimer.com] [src: tenancy.py] [src: insights.py:349]
- **Entry route:** "Bring XCTimer to your district" email today. A demo is the realistic first step. Longer sales cycle than coaches.

### 4. The Community Fun-Run / 5K Organizer
- **Who:** volunteer or small-club organizer of a charity 5K, Turkey Trot or fun run.
- **Goals:** online registration, bibs, results, on a tiny budget.
- **Frustrations:** hiring a timer and paying for software for a small event.
- **Why XCTimer:** `/host` is already self-serve: free to build, one-time fee to go live. [src: https://xctimer.com/host] [src: square.py]
- **Note:** this is the only segment that can truly sign up today, so it is the best segment for early organic tests and proof. It is also the weakest fit for recurring monthly revenue: the fee is per event.

## Pain Points & Value Props

| Pain | XCTimer value prop | Proof |
|---|---|---|
| Timing companies, chip mats and big invoices | Time from a phone you already own | [src: https://xctimer.com] [src: phone.py] |
| Roster spreadsheets, wrong bibs | Upload anything, get clean roster and bib stickers | [src: schools.py] [src: pdfs.py] |
| Volunteers need training and accounts | Helpers scan a QR and start timing | [src: meets.py] |
| Parents ask "what were the results?" all afternoon | Live results link and QR | [src: xc.py:2645] |
| Each school re-enters athletes | Shared district roster | [src: https://xctimer.com] [src: tenancy.py] |
| Waiver paper chasing | Parent e-sign link, audit PDF | [src: waivers.py] |
| Hand-scored heat sheets | Photograph the marked sheet; AI reads it in | [src: track.py] |
| Fun-run setup friction | Build free, pay one fee to go live | [src: https://xctimer.com/host] |

## Positioning Statement

**For** junior high/middle school coaches, athletic directors and district administrators (and the community fun-run organizers beside them) **who** run XC and track meets on tight budgets and volunteer help, **XCTimer is** the meet manager that runs the whole meet from a phone: rosters, bibs, timing, scoring and live results in one place. **Unlike** traditional timing setups with chip mats and consoles, or bundles of spreadsheets and desktop software, **XCTimer** needs no hardware, no timing company, and no training for volunteers. [src: https://xctimer.com]

Differentiation to test (not proven): free trial then simple monthly plan PROVISIONAL(Q-0005); district-wide shared rosters; live spectator experience.

## Competitor Snapshot

| Competitor | What they are | Where they overlap | Where XCTimer can differ | Source |
|---|---|---|---|---|
| Athletic.net | Main XC/track platform for coaches: team rosters, meet entries, results, live splits; free basic meet registration, paid "Site Supporter" tools. Ohio's OHSAA moves entries to it for 2026. | Entries, results, live results, meet hosting | Phone-first timing, AI roster import, district-wide workflow. Likely entrenched: do not position as a replacement; position as the meet-day tool. | [src: https://support.athletic.net/article/0o5pp2asiu-creating-a-cross-country-meet-1-introduction] [src: https://support.athletic.net/article/vqu1tq1k4q-features-for-event-directors-and-timers] |
| RaceTab (MileSplit) | Free meet management software for track and XC; positioned as a cheap alternative to Hy-Tek. | Meet management, scoring | A free incumbent, so price alone will not win. Differentiate on phone timing and live results. | [src: https://ia.milesplit.com/articles/60765] |
| Hy-Tek Meet Manager | Long-time industry-standard desktop meet manager. Resellers list it at $395.00 (Silver, adds XC scoring). | Meet management, scoring | No desktop install; works on phones | [src: https://flashtiming.com/meet-management] |
| FlashTiming XC kit | Hardware XC timing kits from $795.00, Meet Manager not included | Timing | Replaces hardware with phones | [src: https://flashtiming.com/solutions-b/cross-country-solutions] |
| FinishLynx / RaceResult | Photo-finish, video and RFID timing, usually via a timing company | Timing | No hardware or timer fee; accuracy gap must be addressed honestly | [src: https://www.finishlynx.com/cross-country-timing-triad/] [src: https://www.tracksidetiming.com/about-us.html] |
| PBKeeper | Phone timing app for track/XC, per its listing no subscription or account | Phone timing | Full meet workflow (roster, scoring, public results) | [src: https://play.google.com/store/apps/details?id=com.pbkeeper] |
| RunSignup | Race registration and race-director tools with timing integrations; says free tools for directors | Fun-run registration | Built-in bibs, timing and results in one self-serve flow. Check their current pricing before comparing. | [src: https://info.runsignup.com] |

**Not checked:** Direct Athletics and Athletic.net pricing; only partial sourcing found. Do not name prices or make comparative claims in ads without re-verification. Meta policy also limits comparative claims about named competitors, so keep ads about XCTimer's own strengths.

## Messaging Pillars

1. **Your phone is your timing system.** No chip mats, no timing company, no invoice. Proof: phone timing, QR helpers, robot-vision camera. [src: phone.py] [src: https://xctimer.com]
2. **From messy roster to live results in one place.** AI roster import, bib stickers, scoring, a results link parents can open. Proof: [src: schools.py] [src: xc.py:2645]
3. **Built for schools and districts.** Shared rosters, isolated district data, role-based access, e-sign waivers, honest privacy posture (designed with student privacy in mind, not a compliance claim). Proof: [src: tenancy.py] [src: waivers.py] [src: https://xctimer.com/security]

Supporting offer line (PROVISIONAL): "Free 30-day trial, then monthly" PROVISIONAL(Q-0003); price PROVISIONAL(Q-0005). Do not run any trial ad until signup exists.

## Next Steps for Rob

- [ ] Confirm the trial contents PROVISIONAL(Q-0003) and plan price PROVISIONAL(Q-0005).
- [ ] Decide on a tracking pixel vs. the site's "no tracking" promise.
- [ ] Approve a coach self-serve signup WP (the main blocker).
- [ ] Until then, run organic posts for fun-run organizers and spring-track coaches.
