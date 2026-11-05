# Facebook / Instagram Playbook: Free-Tier SaaS Signup Funnel (XCTimer)

> The product is XCTimer (ADR-0006). Do not insert prices or plan limits until Rob answers Q-0003.
> Everything here is a plan for Rob to run. Nothing in this doc has been set up, spent or published. Steps tagged **[Rob-only]** need Rob's logins, payment or approval.

## Summary

- **Goal:** get business owners to sign up for a free tier of XCTimer, activate, and later convert to paid.
- **Path:** Phase 1 = organic, $0 [src: ADR-0007], then a small paid test, then scale only what the data supports.
- **Funnel events (Meta standard names):** `PageView` → `Lead` → `CompleteRegistration` (free signup) → `StartTrial` or a chosen activation event → `Subscribe` (paid). `CompleteRegistration`, `Lead`, `StartTrial` and `Subscribe` are listed standard events [src: https://developers.facebook.com/docs/meta-pixel/reference/]; `PageView` fires automatically from the Pixel base code and is not in that reference table, so confirm it in Test Events. [src: https://www.facebook.com/business/help/402791146561655]
- **Tracking:** Meta Pixel in the browser plus Conversions API from the server, de-duplicated by a shared `event_id`. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events]
- **Budget:** Phase 1 = organic, $0 (ADR-0007). Paid rungs (~$10/day, ~$30/day) are PROVISIONAL(Q-0002) and only start if Rob chooses.
- **Accounts:** Rob has a Business account and a Page, no ad account (ADR-0010). Setup is Phase A organic now, Phase B Pixel optional, Phase C ad account later.
- **Decisions Rob must make first:**

| Open question | Blocks |
|---|---|
| Q-0001 Which product | All product-specific copy, audiences, landing page |
| Q-0002 Budget / organic-only start | Paid phase, budget ladder |
| Q-0003 Free tier contents, paid prices | Offer copy, CAC/payback targets |
| Q-0004 (answered, ADR-0010) | Business account and Page exist; ad account deferred to Phase C |

## Account Setup Checklist

All steps are **[Rob-only]**: they need Rob's identity, logins or payment details. Rob already has a Meta Business account and a Facebook Page, and has no ad account yet (Q-0004 answered; ADR-0010). Skip any step already done. No ad account is needed until Phase C.

### Phase A: now, organic ($0 [src: ADR-0007])

Verify and tune the existing Page. Nothing here costs money.

- [ ] **[Rob-only]** Confirm the Page is attached to the Business account (business.facebook.com). Turn on two-factor authentication on Rob's personal Facebook login (house advice, not a cited Meta rule). [src: https://www.facebook.com/business/help/1710077379203657]
- [ ] **[Rob-only]** Name the Page **XCTimer**.
- [ ] **[Rob-only]** Set the Page category (pick the closest Meta offers for a software product), profile image, cover image and About text. About text may only say what XCTimer does today; check it against xctimer.com before saving.
- [ ] **[Rob-only]** Set the Page call-to-action button to **Sign Up**, linking to `https://xctimer.com/host?utm_source=facebook&utm_medium=social&utm_campaign=firstrace&utm_content=page_cta` (landing URL settled in docs/marketing/funnel-spec.md; /host is the landing page until a dedicated page is built).
- [ ] **[Rob-only]** Verify the xctimer.com domain in the Business account (Brand Safety → Domains; DNS TXT record or meta-tag method). [src: https://www.facebook.com/business/help/286768115176155]
- [ ] **[Rob-only]** Add any other admins (at least one second admin for recovery).
- [ ] **[Rob-only]** Optional: link or create an Instagram professional account and connect it to the Page (needed later for Instagram placements).

### Phase B: optional now (tracking)

- [ ] **[Rob-only]** Create the Pixel (dataset) in Events Manager under the Business account. No ad account is required to create it. Keep the Pixel ID; it is not a secret, but the CAPI access token is (see Tracking Plan).
- [ ] **[Rob-only]** Confirm the website has a published privacy policy and cookie/consent handling (see Compliance) before the Pixel is installed.

### Phase C: later, paid (only when Rob chooses to start ads)

- [ ] **[Rob-only]** Create the ad account inside the Business account. Set currency and time zone correctly at creation; Meta restricts changing the time zone later. [src: https://www.facebook.com/business/help/754049591334898]
- [ ] **[Rob-only]** Add a payment method to the ad account.
- [ ] **[Rob-only]** Set an account spending limit that matches the chosen budget rung PROVISIONAL(Q-0002). [src: https://www.facebook.com/business/help/764293677236889]
- [ ] **[Rob-only]** Connect the Pixel (Phase B) to the ad account.
- [ ] **[Rob-only]** Accept Meta terms prompts (e.g. custom audience terms) when they appear; these are legal acceptances only the account owner can make.

## Tracking Plan

Use the Pixel (browser) and Conversions API (server) together so events survive ad blockers and browser privacy limits, and de-duplicate them with a matching `event_id` and `event_name`. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events]

### Events

| Event (Meta standard name) | Meaning for XCTimer | Where it fires | Source |
|---|---|---|---|
| `PageView` | Any page load | Pixel base code on every page of the marketing site and app | Pixel |
| `Lead` | Visitor shows intent without full signup (e.g. demo request, waitlist or newsletter form submit) | On form-submit success, not on button click | Pixel + CAPI |
| `CompleteRegistration` | Free account created | Server-side after account row is created; Pixel on the post-signup confirmation page | Pixel + CAPI |
| `StartTrial` **or** an activation event | User did the one action that predicts retention (Rob picks it for XCTimer; if the product has no trial, use `StartTrial` only if it is truthful, otherwise send a custom event, e.g. `ActivatedUser`) | Server-side when the activation action is first completed | CAPI (Pixel optional) |
| `Subscribe` | Moved from free to a paid plan | Server-side when billing confirms the subscription | CAPI |

Notes:
- Standard event names are case-sensitive; do not rename them. Use custom events only where no standard event fits. [src: https://www.facebook.com/business/help/2254103654917599]
- Do not use `Purchase` for a subscription; use `Subscribe`. If a value is sent, include `value` and `currency`, and use actual billed amounts only (never guessed).
- Send each event once per action. Generate `event_id` at the moment of the action and pass the same ID to the Pixel and CAPI.
- Send only the customer information parameters Meta documents (hashed email, etc.) and only with a lawful basis and consent where required. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters]
- Never send sensitive data (health information, financial information, credit card or social security numbers) in any event or parameter, and never use event names that imply sensitive categories. Passwords: house rule. [src: https://www.facebook.com/legal/technology_terms]

### Verification (Rob or the developer runs these)

- [ ] **[Rob-only]** Install Meta Pixel Helper in the browser and confirm `PageView` fires once per page.
- [ ] **[Rob-only]** In Events Manager → Test Events, confirm each event arrives from both Pixel and server, and shows as de-duplicated. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api]
- [ ] Do not optimize any campaign for an event until the test shows it firing correctly.

### Secrets handling

- The Conversions API access token and any app secret live **only** in environment variables (e.g. `META_CAPI_ACCESS_TOKEN`, `META_PIXEL_ID`) and are never committed, logged or pasted into docs.
- Keep `.env` files git-ignored; ship a `.env.example` containing variable names with empty values.
- Generate the token in Events Manager → Settings → Conversions API **[Rob-only]**; rotate it if it is ever exposed. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/get-started]

### UTM naming convention

Lowercase, hyphen-separated, no spaces. Every ad and every organic link to the site carries UTMs so the analytics tool and Meta can be reconciled.

| Param | Convention | Example |
|---|---|---|
| `utm_source` | platform | `facebook`, `instagram`, `fb-group` |
| `utm_medium` | `paid-social`, `organic-social`, `group-post` | `paid-social` |
| `utm_campaign` | `{phase}-{objective}-{yyyymm}` | `test-leads-202611` |
| `utm_content` | `{angle}-{format}-{variant}` | `pain-saving-time-img-a` |
| `utm_term` | audience name (ad set) | `interest-core-a` |

Use Meta's dynamic URL parameters in ads only where they do not break this scheme. [src: https://www.facebook.com/business/help/1016122818401732]

## Funnel & KPIs

All targets below are placeholders until Rob supplies Q-0002/Q-0003 and the first weeks of real data exist.

### Definitions and formulas

| KPI | Formula | Notes |
|---|---|---|
| CTR (link) | link clicks ÷ impressions | Use link CTR, not all-clicks CTR |
| CPC (link) | spend ÷ link clicks | |
| Landing-page view rate | landing page views ÷ link clicks | Low rate = slow page or tracking gap |
| Visitor→signup | `CompleteRegistration` ÷ landing page views | |
| Cost per signup | spend ÷ `CompleteRegistration` | |
| Signup→activated | activation events ÷ `CompleteRegistration` (same cohort) | Cohort by signup week |
| Activated→paid | `Subscribe` ÷ activation events (same cohort) | Paid conversion lags; allow time |
| Cost per paid | spend ÷ `Subscribe` | |
| CAC | (ad spend + any paid tools/creative) ÷ new paying customers | Count organic-only customers separately |
| Payback (months) | CAC ÷ (monthly price × gross margin) | Needs Q-0003 prices |

### Targets (all PROVISIONAL)

| KPI | Target | Status |
|---|---|---|
| Link CTR | to be set from first 2 weeks of data | PROVISIONAL(Q-0002) |
| Cost per signup | max acceptable cost to be set once price is known | PROVISIONAL(Q-0003) |
| Signup→activated | to be set from observed baseline | PROVISIONAL(Q-0003) |
| Activated→paid | to be set from observed baseline | PROVISIONAL(Q-0003) |
| CAC | must be below the amount payback target allows | PROVISIONAL(Q-0003) |
| Payback period | Rob decides acceptable months | PROVISIONAL(Q-0003) |

No benchmark numbers are quoted here; do not copy industry averages in as targets. Use your own baseline.

## Campaign Structure

### Phase 1: Organic-first ($0 [src: ADR-0007])

- Run the Organic Playbook below for the first weeks, with the Pixel and CAPI already live so every visitor and signup is measured.
- Purpose: learn which problems and phrases resonate, collect first signups, and gather creative angles that can be reused in ads.
- Exit criteria to Phase 2 (Rob decides): tracking verified; landing page converting visitors to signups at some measurable rate; at least a handful of real signups so activation can be observed; Rob approves a budget rung PROVISIONAL(Q-0002).

### Phase 2: Paid test

**Objective choice: Leads vs Sales** (Meta's current Outcome-Driven objectives: Awareness, Traffic, Engagement, Leads, App promotion, Sales). [src: https://www.facebook.com/business/help/1438417719786914]

| Option | Use when | Trade-off |
|---|---|---|
| **Sales** objective, optimize for `CompleteRegistration` (website conversion) | Pixel/CAPI verified and the signup event fires reliably | Optimizes for the free signup on your own site; best fit for a self-serve funnel |
| **Leads** objective (website conversion location, optimize for `Lead`) | Early on, when signup volume is too low to exit learning, or the offer is demo/waitlist | More volume of a cheaper, shallower event; lower intent |
| Traffic | Avoid for signup goals | Optimizes for clicks, not people who sign up |

Recommendation: start with Leads/`Lead` only if `CompleteRegistration` volume is too thin; move to Sales/`CompleteRegistration` as soon as volume allows. Meta's delivery system needs roughly 50 optimization events per ad set per week to leave the learning phase, so a very small budget cannot optimize on a rare event. [src: https://www.facebook.com/business/help/269269737396981] [src: https://www.facebook.com/business/help/112167992830700] Optimizing for `Subscribe` is not realistic until paid volume exists.

**Structure (one campaign, kept simple):**

| Level | Setup |
|---|---|
| Campaign | One campaign, Advantage campaign budget off at first so Rob controls per-ad-set spend |
| Ad set A | Interest / job-role audience (details below) |
| Ad set B | Broad within country, no interests (let delivery find buyers) |
| Ad set C | Retargeting: website visitors and engaged Page/Instagram users (opens once there is enough audience size) |
| Ads | 2–3 per ad set: one pain-point angle, one outcome angle, one social-proof angle **only if real, permitted proof exists** |

Keep the number of ad sets low so each gets enough events; splitting a small budget across many ad sets starves them. [src: https://www.facebook.com/business/help/112167992830700]

**Audiences**
- **Interests / job titles / behaviors:** pick from Meta's targeting options that match XCTimer's buyer for XCTimer. Keep to 1–2 themes per ad set. Detailed-targeting options change; check availability in Ads Manager **[Rob-only]**. [src: https://www.facebook.com/business/help/182371508761821]
- **Lookalikes:** only after there is a source audience of real signups or paying customers large enough for Meta to build one (Meta states a minimum source size in the audience tool). Prefer a `Subscribe` or activated-user source over all signups. [src: https://www.facebook.com/business/help/164749007013531]
- **Retargeting:** site visitors (Pixel) and people who engaged with the Page. Exclude people who already signed up (`CompleteRegistration` custom audience). Use only visitors from sites that have the privacy notice in place.
- **Exclusions:** existing customers, employees, anyone already signed up.

**Placements**
- Start with Advantage+ placements (automatic) so Meta can find the cheapest results across Facebook Feed, Instagram Feed/Stories/Reels. [src: https://www.facebook.com/business/help/965529646866485]
- After enough data, review placement breakdowns; exclude a placement only if it clearly gets clicks but no signups.
- Prepare creative in both 1:1 / 4:5 and 9:16 so Stories/Reels are not cropped badly.

**A/B test design**
- Test **one variable at a time**: angle (pain vs outcome), then format (image vs short video), then headline/CTA, then landing page.
- Use Meta's A/B test tool in Ads Manager so audiences do not overlap. [src: https://www.facebook.com/business/help/1738164643098669]
- Pre-register before launch: hypothesis, the one metric that decides (cost per signup), and minimum run length (suggested: 7 days, PROVISIONAL(Q-0002)) so results are not judged on noise.
- Do not edit a running test ad (edits can reset learning). Duplicate to change. [src: https://www.facebook.com/business/help/112167992830700]
- Log each test in a simple table: date, variable, variants, result, decision.

## Budget Ladder

Phase 1 = organic, $0 (ADR-0007). Paid amounts below are PROVISIONAL(Q-0002). Rob chooses one rung; none is a recommendation to spend, and no ad account exists until Phase C.

| Rung | Daily spend | What it buys you | Move up when |
|---|---|---|---|
| 0: Phase 1 = organic, $0 [src: ADR-0007] | $0 [src: ADR-0007] | Learning, first signups, creative ideas | Tracking verified and first signups seen |
| 1: Small test | ~$10/day PROVISIONAL(Q-0002) | One ad set at a time; directional data only; likely too small to exit learning on `CompleteRegistration` | Cost per signup within target for a full test period PROVISIONAL(Q-0003) |
| 2: Real test | ~$30/day PROVISIONAL(Q-0002) | 2–3 ad sets, real A/B tests, retargeting | Activation and paid conversion are healthy PROVISIONAL(Q-0003) |

Rules:
- **[Rob-only]** Set the ad account spending limit to match the rung before turning anything on.
- Raise budgets in modest steps and not more than once every few days; large jumps can count as a significant edit and reset learning. [src: https://www.facebook.com/business/help/942374239243867]
- Budget is per day per campaign or ad set; check the lifetime total against Rob's monthly ceiling PROVISIONAL(Q-0002).
- Drop a rung if cost per signup or CAC breaks the target for two consecutive review weeks.

## Organic Playbook

**All posting is Rob's to do or approve [Rob-only]. Nothing here is auto-published.**

### Page setup
- [ ] **[Rob-only]** Page name, profile image and cover image consistent with XCTimer branding.
- [ ] **[Rob-only]** Fill in About, website URL (with UTMs), category and a clear call-to-action button (e.g. Sign Up / Learn More).
- [ ] **[Rob-only]** Pin a post that explains in one sentence what XCTimer does and links to signup.
- [ ] **[Rob-only]** Turn on Messenger/auto-reply with an honest away message.

### Facebook Groups etiquette (no spam)
- Join groups where the target buyers genuinely gather; read the rules first. Many groups ban promotion.
- Spend time being useful first: answer questions, share how-tos, no links in the first interactions.
- Disclose affiliation when mentioning XCTimer ("I work on...").
- Post a link only where rules allow it, or ask the admin for permission **[Rob-only]**.
- Never post the same text in many groups, never tag people who did not ask, never use fake accounts or fake testimonials.
- Reply to comments on your posts, including critical ones, politely and honestly.
- Meta can restrict accounts for spammy behavior. [src: https://transparency.meta.com/policies/community-standards/spam/]

### Posting cadence (starting suggestion; adjust to what Rob can sustain)

| Channel | Cadence | Content mix |
|---|---|---|
| Page | 2–3 posts/week | Tips for the buyer's job, product walkthrough clips, behind-the-scenes, one signup CTA post per week |
| Instagram (optional) | 2 posts or Reels/week | Reuse Page content, short vertical video |
| Groups | 2–3 helpful replies/week, 1 promo post/month at most, only where allowed | Answers and resources first |

### Reply SLA
- Comments and Messenger: reply within 1 business day; same day where possible.
- Signup or support questions: reply within 1 business day with a direct answer or a link.
- Negative comments: reply within 1 business day, publicly acknowledge, move to DM; never delete honest criticism.
- Log recurring questions; they become FAQ content and ad angles.

## Compliance

Rob must read the current policy before launching; policies change. [src: https://transparency.meta.com/policies/ad-standards/]

- [ ] **Honest claims.** Ads and landing page may only say what XCTimer really does today. Every claim should be traceable to the live product or code before use. Meta prohibits deceptive commercial practices (e.g. deceptive pricing, unauthorized endorsements) [src: https://transparency.meta.com/policies/ad-standards/fraud-scams/unacceptable-business-practices/]. House rule on top of that: no fake urgency, no "guaranteed" results, no invented statistics, testimonials or customer logos.
- [ ] **Free means free.** If the ad says "free", the free tier must really be free without a card, and the landing page must say what is and isn't included PROVISIONAL(Q-0003).
- [ ] **Personal attributes.** Do not imply you know the viewer's personal attributes (e.g. "Are you struggling with debt?"). Write about the business or the task instead. [src: https://transparency.meta.com/policies/ad-standards/objectionable-content/privacy-violations-personal-attributes/]
- [ ] **Special Ad Categories.** B2B SaaS is normally not in credit, employment, housing, or social issues categories. If XCTimer touches any of them, declare the category, which limits targeting. [src: https://www.facebook.com/business/help/298000447747885]
- [ ] **Landing page.** The products and services promoted in the ad must match those on the landing page. [src: https://transparency.meta.com/policies/ad-standards/] Meta's spam rules also bar misleading redirects and deceptive page behavior. [src: https://transparency.meta.com/policies/community-standards/spam/] House advice (not a cited Meta rule): load fast, work on mobile, show contact details.
- [ ] **Privacy policy.** A public privacy policy link on the site and in any lead form, naming Meta Pixel/Conversions API use and what data is shared. House advice; Meta's exact privacy-policy requirements for lead forms were not verified here, so check them in the lead form setup screen **[Rob-only]**.
- [ ] **Consent.** Follow applicable law (e.g. GDPR/ePrivacy, CCPA/CPRA) for cookies and data sharing; show a consent banner where required and do not fire Pixel/CAPI events about users who declined. Legal review is Rob's call **[Rob-only]**.
- [ ] **Customer lists.** Upload only lists you have the right to use and accept Meta's custom audience terms **[Rob-only]**. [src: https://www.facebook.com/legal/terms/customaudience]
- [ ] **Creative.** Use only images, music and logos you have rights to. No before/after claims, no third-party trademarks implying endorsement.
- [ ] **Account integrity.** One real account per person; never buy likes, followers or engagement. [src: https://transparency.meta.com/policies/community-standards/inauthentic-behavior/]
- [ ] **Ad approval.** Expect ads to be reviewed before they run; if rejected, fix and resubmit, do not circumvent. [src: https://www.facebook.com/business/help/204798856225114]

## Weekly Review Ritual

**Rob, once a week (about 30 minutes), same day each week. Don't judge a result before it has had a fair test period.**

### Checklist
- [ ] Events Manager: are all five events still firing and de-duplicated? Any warnings?
- [ ] Ads Manager: spend, impressions, link CTR, CPC, landing page views, `CompleteRegistration`, cost per signup (per ad set and per ad).
- [ ] Product data: signups this week, activated, paid (by signup cohort). Compute signup→activated and activated→paid.
- [ ] Organic: Page reach/engagement, group posts, replies outstanding past the SLA.
- [ ] Compliance: any rejected ads, policy notices, account-quality warnings.
- [ ] Update the test log and write one sentence on what was learned.

### Decision rules

Thresholds are for Rob to set; ask "against the target Rob chose" rather than copy a number. PROVISIONAL(Q-0003)

| Situation (against target) | Decision |
|---|---|
| Ad or ad set has spent enough to be judged (at least a full test period, PROVISIONAL(Q-0002)) and cost per signup is clearly worse than the target, with no activation | **Kill** (pause; keep the creative notes) |
| Ad has high CTR but low visitor→signup | **Keep, fix the landing page**; not an ad problem |
| Ads convert but signups don't activate | **Keep spend flat**; fix onboarding before scaling |
| Cost per signup near target, results mixed or sample small | **Keep**; run one more full test period, change one variable |
| Cost per signup and cost per paid both at or better than target for two consecutive weeks, activation healthy | **Scale** by a modest step, not a jump; re-check next week |
| CAC above what payback target allows after paid conversions have had time to arrive | **Cut back** a rung |
| Tracking broken or events missing | **Pause optimization** decisions until fixed |

- Never kill or scale on a single day's numbers.
- Record every decision with the date and reason in the test log.
- Product-specific copy and audiences live in the XCTimer-specific docs (ADR-0006, ADR-0013).

## Source Check

Checked 2026-11-05. Fetched each URL; many Meta Help Center pages return only their title to a non-browser fetch, marked "title only" (QA/Rob should open these in a browser). "removed" rows are URLs no longer cited in this doc.

| URL | Status | Date checked | Note |
|---|---|---|---|
| https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events | OK | 2026-11-05 | Dedup by event_id + event_name confirmed. |
| https://developers.facebook.com/docs/marketing-api/conversions-api/get-started | OK | 2026-11-05 | Generate access token under Events Manager > Settings confirmed. |
| https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters | OK | 2026-11-05 | Hashed email (em) confirmed. |
| https://developers.facebook.com/docs/marketing-api/conversions-api/using-the-api | OK | 2026-11-05 | Test Events tool / test_event_code confirmed. |
| https://developers.facebook.com/docs/meta-pixel/reference/ | OK (added) | 2026-11-05 | Lists CompleteRegistration, Lead, StartTrial, Subscribe. PageView is NOT in its table, so claim reworded. |
| https://transparency.meta.com/policies/ad-standards/ | fixed | 2026-11-05 | Intro page: confirms landing page must match ad. Did NOT support the sensitive-data claim, so that claim moved to Business Tools Terms. |
| https://transparency.meta.com/policies/ad-standards/content-specific-restrictions/personal-attributes/ | removed | 2026-11-05 | HTTP 404. |
| https://transparency.meta.com/policies/ad-standards/deceptive-practices/misleading-or-false-claims/ | removed | 2026-11-05 | HTTP 404. |
| https://transparency.meta.com/policies/ad-standards/deceptive-practices/non-functional-landing-page/ | removed | 2026-11-05 | HTTP 404; no Meta page found for a standalone non-functional-landing-page rule. Claim cut to the cited match rule; rest labelled house advice. |
| https://transparency.meta.com/policies/ad-standards/fraud-scams/unacceptable-business-practices/ | OK (added) | 2026-11-05 | Page titled "Prohibited Commercial Practices": deceptive pricing, unauthorized endorsements. Does not name fake urgency/testimonials, so those are marked house rules. |
| https://transparency.meta.com/policies/ad-standards/objectionable-content/privacy-violations-personal-attributes/ | OK (added) | 2026-11-05 | "Ads must not contain content that asserts or implies personal attributes"; "Are you 18 years old?" example. |
| https://transparency.meta.com/policies/community-standards/inauthentic-behavior/ | OK | 2026-11-05 | Covers fake accounts and artificially inflated popularity. |
| https://transparency.meta.com/policies/community-standards/spam/ | OK | 2026-11-05 | Spam standard; covers misleading redirects, deceptive links, buying engagement. |
| https://www.facebook.com/business/help/1016122818401732 | OK (title only) | 2026-11-05 | "Add URL Parameters to Your Meta Ads"; dynamic-parameter detail not retrievable. |
| https://www.facebook.com/business/help/112167992830700 | OK (title only) | 2026-11-05 | "About the Learning Phase"; body not retrievable. |
| https://www.facebook.com/business/help/1438417719786914 | OK (added, title only) | 2026-11-05 | "How to choose the right ad objective"; six objectives per search summary, body not retrievable. |
| https://www.facebook.com/business/help/164749007013531 | OK (title only) | 2026-11-05 | "About Lookalike Audiences"; minimum source size not confirmed (playbook defers to the audience tool). |
| https://www.facebook.com/business/help/1710077379203657 | fixed | 2026-11-05 | Page is business portfolio creation. 2FA claim detached (marked house advice); privacy-policy claim no longer cited to it. |
| https://www.facebook.com/business/help/1738164643098669 | OK (title only) | 2026-11-05 | "About A/B Testing". |
| https://www.facebook.com/business/help/182371508761821 | OK (title only) | 2026-11-05 | "About Detailed Targeting". |
| https://www.facebook.com/business/help/204798856225114 | OK (title only) | 2026-11-05 | "About Ads In Review". |
| https://www.facebook.com/business/help/2254103654917599 | OK (added, search summary) | 2026-11-05 | Best practices for standard event setup; case-sensitivity per search summary, body not retrievable. |
| https://www.facebook.com/business/help/2469972959933236 | removed | 2026-11-05 | HTTP 404; replaced by legal/terms/customaudience. |
| https://www.facebook.com/business/help/269269737396981 | OK (added, search summary) | 2026-11-05 | "About learning limited": ~50 optimization events in the week after last significant edit, per search summary. |
| https://www.facebook.com/business/help/286768115176155 | OK (title only) | 2026-11-05 | "About Domain Verification"; DNS TXT / meta-tag detail not retrievable, confirm in UI. |
| https://www.facebook.com/business/help/298000447747885 | OK (title only) | 2026-11-05 | "How to Choose a Special Ad Category". |
| https://www.facebook.com/business/help/402791146561655 | OK (title only) | 2026-11-05 | Page title "Specifications for Meta Pixel Standard Events"; body not retrievable. Used only for PageView note. |
| https://www.facebook.com/business/help/517257253637283 | removed | 2026-11-05 | HTTP 404; replaced by 1438417719786914. |
| https://www.facebook.com/business/help/754049591334898 | OK (added, title only) | 2026-11-05 | Time zone change page; replaces 910137316041095 on ad account setup. |
| https://www.facebook.com/business/help/764293677236889 | OK (added, title only) | 2026-11-05 | "Change your Ad Account Spending Limit"; replaces 910137316041095 on spending limit. |
| https://www.facebook.com/business/help/910137316041095 | removed | 2026-11-05 | "Add an ad account to a portfolio": did not support currency/time zone/spending-limit claims; replaced. |
| https://www.facebook.com/business/help/942374239243867 | OK (added, search summary) | 2026-11-05 | "Last Significant Edit": audience/creative/optimization changes count; budget/bid depends on magnitude. |
| https://www.facebook.com/business/help/965529646866485 | OK (title only) | 2026-11-05 | Advantage+ placements delivery page. |
| https://www.facebook.com/legal/technology_terms | OK (added) | 2026-11-05 | Business Tools Terms 1.h: no health/financial/sensitive data, no SSN/credit card numbers, no event names implying sensitive categories. |
| https://www.facebook.com/legal/terms/customaudience | OK (added) | 2026-11-05 | Customer List Custom Audiences Terms: rights/lawful basis and opt-out removal confirmed. |
