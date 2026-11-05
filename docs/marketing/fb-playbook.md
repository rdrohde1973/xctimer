# Facebook / Instagram Playbook: Free-Tier SaaS Signup Funnel ({PRODUCT})

> Product-neutral on purpose. Q-0001 (which product) is open, so the product is written as `{PRODUCT}`. Do not insert product claims, prices or plan limits until Rob answers Q-0001 and Q-0003.
> Everything here is a plan for Rob to run. Nothing in this doc has been set up, spent or published. Steps tagged **[Rob-only]** need Rob's logins, payment or approval.

## Summary

- **Goal:** get business owners to sign up for a free tier of `{PRODUCT}`, activate, and later convert to paid.
- **Path:** organic-first at $0 PROVISIONAL(Q-0002), then a small paid test, then scale only what the data supports.
- **Funnel events (Meta standard names):** `PageView` → `Lead` → `CompleteRegistration` (free signup) → `StartTrial` or a chosen activation event → `Subscribe` (paid). [src: https://www.facebook.com/business/help/402791146561655]
- **Tracking:** Meta Pixel in the browser plus Conversions API from the server, de-duplicated by a shared `event_id`. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events]
- **Budget:** three rungs ($0, ~$10/day, ~$30/day), all PROVISIONAL(Q-0002).
- **Decisions Rob must make first:**

| Open question | Blocks |
|---|---|
| Q-0001 Which product | All product-specific copy, audiences, landing page |
| Q-0002 Budget / organic-only start | Paid phase, budget ladder |
| Q-0003 Free tier contents, paid prices | Offer copy, CAC/payback targets |
| Q-0004 Business account, Page, ad account access | Account setup, tracking |

## Account Setup Checklist

All steps are **[Rob-only]**: they require Rob's identity, logins or payment details. PROVISIONAL(Q-0004) (who owns/has access to existing assets is not yet known; skip any step already done).

- [ ] **[Rob-only]** Create or locate the Meta Business portfolio (Business Manager) at business.facebook.com, using a business email. Turn on two-factor authentication on Rob's personal Facebook login. [src: https://www.facebook.com/business/help/1710077379203657]
- [ ] **[Rob-only]** Create the Facebook Page for `{PRODUCT}` (or claim the existing one) and add it to the business portfolio. Add a second admin for recovery.
- [ ] **[Rob-only]** Link or create an Instagram professional account and connect it to the Page (optional for the organic phase, needed for Instagram placements).
- [ ] **[Rob-only]** Create the ad account inside the business portfolio. Set currency and time zone correctly; both are hard to change later. [src: https://www.facebook.com/business/help/910137316041095]
- [ ] **[Rob-only]** Verify the website domain in Meta Brand Safety → Domains (DNS TXT record or meta-tag method). Needed for conversion event configuration and link ownership. [src: https://www.facebook.com/business/help/286768115176155]
- [ ] **[Rob-only]** Create a Pixel (dataset) in Events Manager and connect it to the ad account. Keep the Pixel ID; it is not a secret, but the CAPI access token is (see Tracking Plan).
- [ ] **[Rob-only]** Add a payment method to the ad account. Do this only when entering the paid phase. Set an account spending limit that matches the chosen budget rung PROVISIONAL(Q-0002). [src: https://www.facebook.com/business/help/910137316041095]
- [ ] **[Rob-only]** Confirm the website has a published privacy policy and cookie/consent handling (see Compliance) before any ad runs.
- [ ] **[Rob-only]** Accept Meta terms prompts (e.g. custom audience terms) when they appear; these are legal acceptances only the account owner can make.

## Tracking Plan

Use the Pixel (browser) and Conversions API (server) together so events survive ad blockers and browser privacy limits, and de-duplicate them with a matching `event_id` and `event_name`. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/deduplicate-pixel-and-server-events]

### Events

| Event (Meta standard name) | Meaning for `{PRODUCT}` | Where it fires | Source |
|---|---|---|---|
| `PageView` | Any page load | Pixel base code on every page of the marketing site and app | Pixel |
| `Lead` | Visitor shows intent without full signup (e.g. demo request, waitlist or newsletter form submit) | On form-submit success, not on button click | Pixel + CAPI |
| `CompleteRegistration` | Free account created | Server-side after account row is created; Pixel on the post-signup confirmation page | Pixel + CAPI |
| `StartTrial` **or** an activation event | User did the one action that predicts retention (Rob picks it once Q-0001 is answered; if the product has no trial, use `StartTrial` only if it is truthful, otherwise send a custom event, e.g. `ActivatedUser`) | Server-side when the activation action is first completed | CAPI (Pixel optional) |
| `Subscribe` | Moved from free to a paid plan | Server-side when billing confirms the subscription | CAPI |

Notes:
- Standard event names are case-sensitive; do not rename them. Use custom events only where no standard event fits. [src: https://www.facebook.com/business/help/402791146561655]
- Do not use `Purchase` for a subscription; use `Subscribe`. If a value is sent, include `value` and `currency`, and use actual billed amounts only (never guessed).
- Send each event once per action. Generate `event_id` at the moment of the action and pass the same ID to the Pixel and CAPI.
- Send only the customer information parameters Meta documents (hashed email, etc.) and only with a lawful basis and consent where required. [src: https://developers.facebook.com/docs/marketing-api/conversions-api/parameters/customer-information-parameters]
- Never send sensitive data (passwords, financial account numbers, health data) in any event parameter. [src: https://transparency.meta.com/policies/ad-standards/]

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

### Phase 1: Organic-first ($0, PROVISIONAL(Q-0002))

- Run the Organic Playbook below for the first weeks, with the Pixel and CAPI already live so every visitor and signup is measured.
- Purpose: learn which problems and phrases resonate, collect first signups, and gather creative angles that can be reused in ads.
- Exit criteria to Phase 2 (Rob decides): tracking verified; landing page converting visitors to signups at some measurable rate; at least a handful of real signups so activation can be observed; Rob approves a budget rung PROVISIONAL(Q-0002).

### Phase 2: Paid test

**Objective choice: Leads vs Sales** (Meta's current Outcome-Driven objectives: Awareness, Traffic, Engagement, Leads, App promotion, Sales). [src: https://www.facebook.com/business/help/517257253637283]

| Option | Use when | Trade-off |
|---|---|---|
| **Sales** objective, optimize for `CompleteRegistration` (website conversion) | Pixel/CAPI verified and the signup event fires reliably | Optimizes for the free signup on your own site; best fit for a self-serve funnel |
| **Leads** objective (website conversion location, optimize for `Lead`) | Early on, when signup volume is too low to exit learning, or the offer is demo/waitlist | More volume of a cheaper, shallower event; lower intent |
| Traffic | Avoid for signup goals | Optimizes for clicks, not people who sign up |

Recommendation: start with Leads/`Lead` only if `CompleteRegistration` volume is too thin; move to Sales/`CompleteRegistration` as soon as volume allows. Meta's delivery system needs roughly 50 optimization events per ad set per week to leave the learning phase, so a very small budget cannot optimize on a rare event. [src: https://www.facebook.com/business/help/112167992830700] Optimizing for `Subscribe` is not realistic until paid volume exists.

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
- **Interests / job titles / behaviors:** pick from Meta's targeting options that match `{PRODUCT}`'s buyer once Q-0001 is answered. Keep to 1–2 themes per ad set. Detailed-targeting options change; check availability in Ads Manager **[Rob-only]**. [src: https://www.facebook.com/business/help/182371508761821]
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

Every amount below is PROVISIONAL(Q-0002). Rob chooses one rung; none is a recommendation to spend.

| Rung | Daily spend | What it buys you | Move up when |
|---|---|---|---|
| 0: Organic only | $0 PROVISIONAL(Q-0002) | Learning, first signups, creative ideas | Tracking verified and first signups seen |
| 1: Small test | ~$10/day PROVISIONAL(Q-0002) | One ad set at a time; directional data only; likely too small to exit learning on `CompleteRegistration` | Cost per signup within target for a full test period PROVISIONAL(Q-0003) |
| 2: Real test | ~$30/day PROVISIONAL(Q-0002) | 2–3 ad sets, real A/B tests, retargeting | Activation and paid conversion are healthy PROVISIONAL(Q-0003) |

Rules:
- **[Rob-only]** Set the ad account spending limit to match the rung before turning anything on.
- Raise budgets in modest steps and not more than once every few days; large jumps can reset learning. [src: https://www.facebook.com/business/help/112167992830700]
- Budget is per day per campaign or ad set; check the lifetime total against Rob's monthly ceiling PROVISIONAL(Q-0002).
- Drop a rung if cost per signup or CAC breaks the target for two consecutive review weeks.

## Organic Playbook

**All posting is Rob's to do or approve [Rob-only]. Nothing here is auto-published.**

### Page setup
- [ ] **[Rob-only]** Page name, profile image and cover image consistent with `{PRODUCT}` branding.
- [ ] **[Rob-only]** Fill in About, website URL (with UTMs), category and a clear call-to-action button (e.g. Sign Up / Learn More).
- [ ] **[Rob-only]** Pin a post that explains in one sentence what `{PRODUCT}` does and links to signup.
- [ ] **[Rob-only]** Turn on Messenger/auto-reply with an honest away message.

### Facebook Groups etiquette (no spam)
- Join groups where the target buyers genuinely gather; read the rules first. Many groups ban promotion.
- Spend time being useful first: answer questions, share how-tos, no links in the first interactions.
- Disclose affiliation when mentioning `{PRODUCT}` ("I work on...").
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

- [ ] **Honest claims.** Ads and landing page may only say what `{PRODUCT}` really does today. Every claim should be traceable to the live product or code before use. No fake urgency, no "guaranteed" results, no invented statistics, testimonials or customer logos. [src: https://transparency.meta.com/policies/ad-standards/deceptive-practices/misleading-or-false-claims/]
- [ ] **Free means free.** If the ad says "free", the free tier must really be free without a card, and the landing page must say what is and isn't included PROVISIONAL(Q-0003).
- [ ] **Personal attributes.** Do not imply you know the viewer's personal attributes (e.g. "Are you struggling with debt?"). Write about the business or the task instead. [src: https://transparency.meta.com/policies/ad-standards/content-specific-restrictions/personal-attributes/]
- [ ] **Special Ad Categories.** B2B SaaS is normally not in credit, employment, housing, or social issues categories. If `{PRODUCT}` touches any of them, declare the category, which limits targeting. [src: https://www.facebook.com/business/help/298000447747885]
- [ ] **Landing page.** Must match the ad, load properly, work on mobile, not be deceptive or non-functional, and show how to contact the business. [src: https://transparency.meta.com/policies/ad-standards/deceptive-practices/non-functional-landing-page/]
- [ ] **Privacy policy.** A public privacy policy link on the site and in any lead form, naming Meta Pixel/Conversions API use and what data is shared. Required for lead ads and good practice for all. [src: https://www.facebook.com/business/help/1710077379203657]
- [ ] **Consent.** Follow applicable law (e.g. GDPR/ePrivacy, CCPA/CPRA) for cookies and data sharing; show a consent banner where required and do not fire Pixel/CAPI events about users who declined. Legal review is Rob's call **[Rob-only]**.
- [ ] **Customer lists.** Upload only lists you have the right to use and accept Meta's custom audience terms **[Rob-only]**. [src: https://www.facebook.com/business/help/2469972959933236]
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
- Revisit this doc after Q-0001 is answered and replace `{PRODUCT}` with product-specific copy in a separate, product-specific playbook.
