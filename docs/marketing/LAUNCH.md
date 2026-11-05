# XCTimer Launch Checklist (one page)

> Plan for Rob; nothing here has been done, posted or spent. Everything tagged **[Rob-only]** needs your logins or approval. Work top to bottom; you do not need to open any other doc.

## Summary

- **What you are launching:** free organic posting (zero ad spend [src: ADR-0007]) aimed at fun-run organizers, sending them to `https://xctimer.com/host`. Offer: "Your first race is free with code FIRSTRACE, then $50 per event." [src: ADR-0014] [src: ADR-0016] [src: road.py:24]
- **Order matters:** deploy, create the code, test the funnel, set up the Page, then post. Do not post the code before step 2 is done and tested [src: docs/marketing/funnel-spec.md].
- **Measurement:** first-party only. The report is at `https://xctimer.com/organizers/attribution` (super admin) [src: road.py:182]. No Meta Pixel at launch [src: ADR-0017].
- **Time needed:** roughly one evening for steps 1 to 5, then 3 posts a week and a 30-minute weekly review.
- **Calendar:** 12 posts over 4 weeks starting Tue 2026-12-01; 9 carry a link and 3 do not [src: docs/marketing/ads.md].

## Before Launch

### 1. Deploy main to xctimer.com

- [ ] **[Rob-only]** Run the deploy command from DEPLOY.md section 6 [src: DEPLOY.md]:

```
ssh rob@10.0.1.167 'ssh rob@5.78.183.9 "cd ~/xctimer && git pull && \
  .venv/bin/python -m py_compile *.py && systemctl --user restart xctimer.service"'
```

- [ ] **[Rob-only]** Version check: `curl -s https://xctimer.com/healthz`. The reply reads `{"status":"ok","version":"..."}` and the version must be `1.110.0-host-friction` or newer (that is main after the host landing/prefill and host-flow fixes [src: app.py:29]). If it is older, the pull did not take: re-run the deploy.
- [ ] **[Rob-only]** Open `https://xctimer.com/host` in a browser and confirm the page loads.

### 2. Create the FIRSTRACE code

- [ ] **[Rob-only]** Log in as super admin and open `https://xctimer.com/organizers`.
- [ ] **[Rob-only]** Add promo code `FIRSTRACE`: discount 100%, "first event only" ticked, max uses left blank [src: ADR-0016] [src: road.py:312].
- [ ] **[Rob-only]** Confirm it shows in the promo list with those settings.

### 3. Test the funnel end to end

- [ ] **[Rob-only]** Open a private/incognito window and paste this link: `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w1-pin`
- [ ] **[Rob-only]** Sign up at /host with a throwaway email you can read; click the magic link in the email [src: docs/marketing/funnel-spec.md].
- [ ] **[Rob-only]** Prefill check: open the event's go-live box. The code field must already show `FIRSTRACE` because the link carried `?code=FIRSTRACE` [src: road.py:1683]. If it is empty, the prefill is broken: stop and tell the team.
- [ ] **[Rob-only]** Go live with that code; it should publish with no payment [src: road.py:1525].
- [ ] **[Rob-only]** Create a second event with the same email and try FIRSTRACE again; it must be refused (first event only) [src: ADR-0014].
- [ ] **[Rob-only]** In your normal window, open `https://xctimer.com/organizers/attribution`. Expect a row with source `facebook`, campaign `firstrace`, and counts for signups, events created, events published and FIRSTRACE used [src: road.py:182].
- [ ] If the row is missing or the counts are wrong, stop and fix before posting. Delete the test event afterwards if you do not want it public.

Note: the report groups by source and campaign only, not by `utm_content`, so it cannot show signups per post [src: road.py:166]. Your test also adds one `firstrace` signup; subtract it when you read the numbers.

### 4. Set up the Facebook Page (playbook Phase A)

All **[Rob-only]**; skip anything already done [src: docs/marketing/fb-playbook.md].

- [ ] Page is attached to your Business account; turn on two-factor authentication on your personal login.
- [ ] Page name `XCTimer`; set category, profile image, cover image and About text. The About text may only describe what XCTimer does today.
- [ ] Call-to-action button = **Sign Up**, link: `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=social&utm_campaign=firstrace&utm_content=page_cta`
- [ ] Verify the xctimer.com domain in the Business account (Brand Safety, Domains).
- [ ] Add a second admin for recovery.
- [ ] Optional: connect an Instagram professional account. Instagram captions have no clickable links, so say "link in bio" and put a UTM link in the bio.
- [ ] Skip the Pixel and the ad account for now (playbook Phases B and C are later).

### 5. Capture the media

- [ ] **[Rob-only]** Build one test event with made-up adult names and capture the screens the posts need (phone timing, /host form, registration page, bib sheet preview, live results, course map). Check each frame for real names, emails or tokens; never include children [src: docs/marketing/ads.md].

## Launch Week

### 6. Schedule the 12 posts

- [ ] **[Rob-only]** In Meta Business Suite, schedule the posts below. Full copy and media for each post are in `docs/marketing/ads.md` (Organic Calendar). Paste the exact link listed here at the end of the copy [src: docs/marketing/ads.md].

| Post | Date | Exact link |
|---|---|---|
| w1-pin | Tue 2026-12-01 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w1-pin` |
| w1-tip | Thu 2026-12-03 | no link |
| w1-demo | Sat 2026-12-05 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w1-demo` |
| w2-how | Tue 2026-12-08 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w2-how` |
| w2-offer | Thu 2026-12-10 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w2-offer` |
| w2-S1 | Sat 2026-12-12 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w2-s1` |
| w3-bibs | Tue 2026-12-15 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w3-bibs` |
| w3-results | Thu 2026-12-17 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w3-results` |
| w3-map | Sat 2026-12-19 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w3-map` |
| w4-ask | Tue 2026-12-22 | no link (a question to organizers) |
| w4-S2 | Thu 2026-12-24 | no link (holiday greeting) |
| w4-cta | Sat 2026-12-26 | `https://xctimer.com/host?code=FIRSTRACE&utm_source=facebook&utm_medium=organic-social&utm_campaign=firstrace&utm_content=w4-cta` |

- [ ] **[Rob-only]** Reply to every comment within 1 business day [src: docs/marketing/fb-playbook.md].
- [ ] **[Rob-only]** 12-24 and 12-26 are holiday-adjacent; shift or drop them, but keep school posts (w2-S1, w4-S2) at 2 or fewer.
- [ ] **[Rob-only]** No testimonials until you have real, permissioned ones.

### 7. Groups outreach

All **[Rob-only]**, since it uses your profile. Message templates are in `docs/marketing/ads.md` (Facebook Groups Outreach Plan).

- [ ] Week 1: list 10 to 15 adult-run groups (running clubs, race organizers, PTA/booster, church and charity events). Record each group's rule on promotion and links; drop groups that ban it.
- [ ] Weeks 1 and 2: 2 to 3 helpful replies per week with no link.
- [ ] Week 2 on: message the admin with the template before posting any link.
- [ ] Week 3 on: one post per allowed group, a different opening for each, always saying "I work on XCTimer", at most 1 promo post per month per group. Link: `https://xctimer.com/host?code=FIRSTRACE&utm_source=fb-group&utm_medium=group-post&utm_campaign=firstrace&utm_content=group-post`
- [ ] Accept a "no" without argument. No fake accounts.

## Weekly Review

**[Rob-only]**, same day each week, about 30 minutes [src: docs/marketing/fb-playbook.md].

- [ ] Open `https://xctimer.com/organizers/attribution` (or the CSV at `/organizers/attribution.csv`; both cover the last 90 days) and note signups, events created, events published and FIRSTRACE used by source [src: road.py:182] [src: road.py:203].
- [ ] In Meta Business Suite, per post: reach, comments, shares, saves, link clicks. Judge posts by link clicks, since the report cannot split by post.
- [ ] Reply to any comment older than 1 business day. Check for policy notices.
- [ ] Write one sentence on what you learned, with the date.

Keep/kill rules (organic; the thresholds are yours to set):

| Situation | Decision |
|---|---|
| Replies or link clicks, and signups appear under that source | **Keep**; make a variation |
| Many clicks, no signups | **Keep the post, fix /host** (copy or form) |
| Signups but no events published | **Keep**; fix the go-live step before posting more |
| No engagement after 7 days | **Kill** that angle; note the lesson [src: docs/marketing/ads.md] |
| A group says no, or a policy notice arrives | **Stop** in that group and tell the team |
| Report numbers look wrong | **Pause decisions** until tracking is fixed |

Never kill or scale on one day of numbers. Signup targets are PROVISIONAL(Q-0002).

## Known Limits

Do not claim any of these in posts or comments [src: docs/marketing/positioning.md]:

- **No waivers on fun runs.** The /host registration form has no waiver step; waivers exist only for school districts [src: waivers.py] [src: road.py:849].
- **Runner entry fees are not paid by card.** Runners pay the organizer by Venmo or at packet pickup; Venmo is an honor system and is not verified [src: road.py:866] [src: road.py:1234].
- **Events are deleted 30 days after the race.** Say "download your results", never "results archive" [src: reap.py].
- Also avoid chip-level accuracy claims, compliance badges, and any price other than the FIRSTRACE offer quoted in the Summary.
- FIRSTRACE works once per organizer; later events pay the per-event fee, PROVISIONAL(Q-0007).

Landing-page copy, the `?code=FIRSTRACE` prefill and the host-flow fixes are built and deployed in step 1 (G1, G2, G3 in the funnel spec) [src: docs/marketing/funnel-spec.md]. Posts and the Page button therefore link to `/host?code=FIRSTRACE&...` so the code is already filled in.

## Later

Paid phase and tracking: pointers only. Do none of this until organic results justify it and you choose to spend.

- Ad account, payment method and spend limit: `docs/marketing/fb-playbook.md`, Phase C **[Rob-only]**.
- Meta Pixel and Conversions API: needs a new ADR first; it conflicts with the privacy page today [src: ADR-0017] [src: docs/marketing/funnel-spec.md].
- Paid ad copy (6 variants) and audience tests: `docs/marketing/ads.md`, Ad Variants and Test Matrix.
- Budget and cost targets: PROVISIONAL(Q-0002).
- **Optional follow-up, needs your approval (G4): onboarding nudge emails** (E1 to E8 in the funnel spec). Not built. It would send real email to organizers, so approve it deliberately. Until then, follow up with hosts by hand [src: docs/marketing/funnel-spec.md].
