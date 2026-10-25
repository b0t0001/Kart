# KART status board

Owned by the manager session and updated at each check-in. The newest entry is at the top. The contract lives in [CONTRACT.md](CONTRACT.md).

## Morning checklist for Dylan
1. Read each chat's overnight decision log:
   - `pi/docs/OVERNIGHT.md`
   - `ios/docs/OVERNIGHT.md`
   - `backend/docs/OVERNIGHT.md`
2. Create the hosted Supabase project (the browser pane has the sign-in tab open), then put the hosted values in `.env`, replacing the `LOCAL SUPABASE` block:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY`
   - `SUPABASE_DB_URL`
   - `SUPABASE_PROJECT_REF`
   - `SUPABASE_ACCESS_TOKEN`
3. Add `ANTHROPIC_API_KEY` to `.env`.
4. Cartesia: create an API key and the Line agent, then add `CARTESIA_API_KEY` and `CARTESIA_AGENT_ID` to `.env`. The iPad chat lists the exact steps in `ios/docs/OVERNIGHT.md`.
5. Run `backend/go_live.sh`; it should print PASS. Then try the merchant console with real Claude (`backend/docs/DEMO.md`). The local stack can be stopped with `supabase stop --workdir backend && colima stop`.
6. Your teammate pulls `main` and runs the CV code on the Pi (`pi/README.md` "Milestone checks", then enrollment of the 10–15 demo props). The Pi needs `.env` at `~/kart/.env` with `ANTHROPIC_API_KEY`.
7. iPad: run it on the real iPad (`ios/docs/OVERNIGHT.md`). Turn Stage Manager off. Check that chimes and voice play well together once the Cartesia Line agent is deployed. The demo controls are a three-finger long press, including "Use offline demo mode" as a fallback.
8. Rehearse the demo with `backend/docs/DEMO.md`, including the live Parmesan beat.

## Log

### 2026-10-25 07:45 · README CV section; iPad replay
- README leads with real-store CV footage (cv-drop.gif) and adds a "How the cart sees" section. The iPad screen for take-0245 was reconstructed from the transcript, cart_events and receipt via tools/ipad_replay.py plus the app's -KartReplay mode (8fc2a1f).

### 2026-10-25 03:35 · video takes done; repo presentable
- Successful store takes at 02:15 and 02:45; their BTS MP4s are on the bts-clips branch (take-0215 with "what Claude saw" insets; take-0245 full plus clips). repo-presentation merged into main (README, ARCHITECTURE, LICENSE, .env.example, privacy scrub; history still has the old details).

### 2026-10-25 02:30 · store shoot
- Demo-video aisles live (layout demo-video: 1A/3A/2A/1B; re-apply after every pre_judging). The 02:15 store take was clean end to end (empty basket at trip start, items spread, cart not rolled). Rolling into new light and a jar next to a box caused re-bills earlier; CV pushed a lighting fix (39349d9), not on the frozen Pi. BTS grabber is extended; the 02:15 clips are being cut first.

### 2026-10-25 01:30 · repo presentation branch
- `repo-presentation` pushed (README rewrite with architecture diagrams, docs/ARCHITECTURE.md, MIT LICENSE, root .env.example); merge after the demo, after a privacy scrub (project ref, Pi IPs, session IDs, third-party PDFs). bts-clips is still pending from the hardware chat.

### 2026-10-25 00:40 · end-to-end passed, BTS recording
- Dylan's 00:14 live end-to-end (real voice, tap-to-pay) billed right at checkout ($7.37); 1 phantom from a nudged jar, removed on the iPad. Agent fix deployed: natural declines clear the deals question (75ac548). BTS: James's laptop grabs /cam/0 overlay frames at 5 Hz; clips go to the bts-clips branch; CV added tools/bts_record.py.

### 2026-10-24 23:35 · Pi on the power bank, cam1 outline refit
- The Pi moved to the 20,000 mAh bank (a 20 min outage: a USB-PD bank with a C-to-C cable never switched on; fixed, throttled 0x0). cam1's floor outline refit inside the paper after the cart move; cam0 unplugged; code still frozen on f329278. Hardware README covers battery, Wi-Fi backup and Tailscale.

### 2026-10-24 22:25 · tap-to-pay on the iPad, fresh end-to-end
- The tap-to-pay build (9c1e5d3) is installed and relaunched with -KartBackend supabase -KartVoice line -KartTapToPay YES; cart 7 reset for a fresh end-to-end. Live bug for after the demo: touching items merge (marinara billed as spaghetti; removal took both). Keep gaps between items.

### 2026-10-24 21:35 · demo freeze, end-to-end under way
- Demo decision: cam1 only (config.cam1.json), Pi frozen on f329278, kart-cv.service autostarts on cart 7 (reboot-proven). Cartesia Pro bought; real voice confirmed from the iPad (relaunched with -KartBackend supabase -KartVoice line). Cart 7 reset with judging stock and member memory on. Tap-to-pay built (0db108f), held for the venue install.

### 2026-10-24 night · CV fixes hold at demo pace
- With the fixes running, the pasta runs ended with the right bill 3/3 (was 1/3, pre-fix). Run 4 at 3–4 s gaps re-billed items (a pending cam0 check crossing the next placement); that's CV's top fix, with a pasta-fast clip coming. CV pushed: a close-up piece joins the other camera's item; one quick Claude retry.

### 2026-10-24 late · floor passes, double count is top bug
- The flattened paper liner passed the 3-drop test (no phantoms). One drop was billed twice (both cams named it), which would trigger a false "Keep the extra?". It's CV's top fix, with a single-drops clip coming. cam0 was knocked 216 px and re-aimed.

### 2026-10-24 late · props enrolled
- 4 props enrolled (pi/gallery, props-final clip). Live: all 4 named right, but 3 CV bugs remain (removal mis-attribution, late-view phantom, liner phantom); CV is fixing them. Catalog now matches the real props (marinara $2.19, Parmesan $4.19; demo bill $7.37). Liner flattened; the 3-drop test and counting clips run after Dylan's dinner.

### 2026-10-24 night · enrollment under way, deals quiet
- One "No thanks" quiets deals for the trip; the route is 6 → 4 → 9 (confirmed on hosted); scissors are the 2 ct pack. Enrollment runs from James's PC: the cams were re-aimed, and the liner shift caused false captures (taping it down; CV is fixing enroll.py). iPad mount CAD pushed.

### 2026-10-24 night · member memory merged, nudges on
- Member memory merged to main (flag off; tag `stable-pre-memory`). Quantity nudges ON by default (the 2nd spaghetti box → "Keep the extra?"). Script route 6 → 4 → 9. Guests' bare "yeah" fixed. Voice agent redeploy pending.

### 2026-10-24 evening · final demo script, conversation fixes
- **Final demo** (`docs/DEMO_PLAN.md`): one natural pasta trip, plus a member Act 2 (capture Leo's party live → fast-forward). Shopping: 4 items, ~$16 at Target Berkeley Central.
- **Voice:** list editing is live. Interaction catalog: 52 scenarios run against the real model. Fixes landing: replan keeps the cart, diet guard, "how much is this?", and more.
- **Backend:** add/remove-plan RPCs, budget, nearby stores, bakery last, chocolate bar added; "that's mine" fully removed.
- **Member memory:** backend and agent done on its branch; iPad in progress.
- **Open:** Cartesia credits (Dylan); 3 KartCore tests to fix after the catalog change (iPad chat); the Target trip.


### 2026-10-24 late afternoon · demo meals, Target layout, nudge fixes
- **Demo plan** (`docs/DEMO_PLAN.md`): two shelf-stable meals (pasta night for 4, game-night nachos for 6). Every item is verified in stock at **Target Berkeley Central** (aisles A12 and A6, ~$29; `docs/TARGET_SHOPPING_CHECKLIST.md`). Kart's lists match 3/3 with the real model.
- **Backend:** the demo catalog is live; switchable store layouts (`db.py layout mini|target-berkeley`; the Target layout is a draft until Dylan confirms); `pre_judging.sh`; mid-trip "short" nudges off (`9f60cd3`).
- **CV:** the final two-camera layout (Brio + Aoozi wide-angle) is supported, with corrupt frames dropped. 131 tests.
- **Member memory** beta: spec approved; being built on its own branch.
- **Waiting on Dylan:** the Target trip (receipt plus aisle-sign photos).


### 2026-10-24 afternoon · real-cart fixes, voice on the iPad, nudges beta
- **CV on the real cart:** basket-floor ROI; rolling no longer fools it; tall items are billed after a 3 s stillness recheck; a big shift is only believed if it explains the change; light and shadow aren't items; judging runs off the camera loop. James's first 5 real clips pass as regression tests. 123 tests.
- **Voice on Dylan's iPad works end to end** (iPadOS 26.7.1): ~1.5–2 s to Kart's first words. Hold-to-talk for loud floors, quiet on chatter, quantities with stock caps, and yes/no to deals by voice.
- **Quantity nudges (BETA, flag `quantity_nudges`, OFF by default; rollback tag `stable-pre-nudges`):** backend live on hosted (verified identical with the flag off), the agent says the nudges, the iPad UI is in progress. CV `claude_count` beta is also off by default.
- **Merchant console** = demo-setup housekeeping. smoke.py 19/19 on hosted.
- **Waiting on Dylan:** the props/catalog decision; whether to add two saved store layouts (mini store vs real store).

### 2026-10-24 late morning · real-Claude tests pass; voice is unblocked
- **Merchant agent on hosted with real Claude: PASS** (`7cfd108`, rerun with `merchant/smoke.py`). All four prompts: preview → Confirm → log → Undo. The parmesan beat reaches the cart 0.1 s after Confirm; owner message → preview takes 3–6 s.
- **CV on hosted:** end-to-end 2/2. The real-Claude identifier got 12/12 on printed-name crops, median 1.6 s (an upper bound; the real props come after enrollment). 87 tests.
- **Hardware (James's PC, real Pi):** 80 tests pass on the Pi, and snap, live and /status work. The cams aren't mounted yet, and the Pi still needs `git pull` and its `.env`.
- **Cartesia:** the key works; voice-token is deployed to hosted (200, short-lived token). The iPad chat is now deploying the Line agent. Dylan approves `cartesia auth login` in the browser.
- New shared rule: no `reset-demo` on hosted from tests or rehearsals (contract v0.11).

### 2026-10-24 morning · HOSTED SUPABASE IS LIVE
- Project **kart** (org KART, West US, free plan, ref `<supabase-project-ref>`). Dylan pasted the keys into `.env`; the manager checked their format without reading them out (anon and service_role roles match the project, the DB URL uses the session pooler, the token is a valid PAT, and the Anthropic key returns HTTP 200).
- **`backend/go_live.sh`: PASS.** Migrations, seed, demo simulation over REST, end-to-end (4 passed, 1 skipped), reset-demo. Cart 7 is idle. The voice-token deploy waits for a Cartesia key.
- Now running: the backend's real-Claude smoke test of the merchant agent; CV's identifier tested against real Claude plus its end-to-end test against hosted; the iPad switching Dylan's real iPad over to hosted.
- **Teammate's Pi:** needs `~/kart/.env` with `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CART_ID=7` and `ANTHROPIC_API_KEY`, sent privately by Dylan. **Not** the service-role key, DB URL or access token.

### 2026-10-24 ~08:00 · morning: merged and tested
- **Merge:** nothing to merge. Everything is on `main`, which is synced with GitHub, and the stale `claude/*` branches are deleted.
- **All automated suites rerun on `main`: 316 tests green** (CV 80 + 2 end-to-end, backend 53 + 5 end-to-end, merchant 42, Edge Function 5, agent 29, iPad 100).
- **Test plan:** [TESTING.md](TESTING.md), a six-rung ladder (automated → one-Mac system → go live → Pi cameras → iPad + voice → demo rehearsal).
- **Routing rule:** chats send cross-chat notices to the manager, never to Dylan; all three have been told.

### 2026-10-24 ~03:40 · check-in
- Backend fixed the iPad's follow-up (`f6e41f3`): a Yes, which puts the product on the plan, now consumes the deal suggestion, so the next deal can be offered right away. Pushed. All three chats are idle and done.

### 2026-10-24 ~02:50 · check-in: all three chats finished their overnight work
- **iPad: DONE overnight** (idle). The app, its Supabase backend and the Line voice agent are built. A fresh reviewer found 1 Critical and 7 Important problems, and all are fixed (`e7c30cd`, `f0acd3f`). Tests: iOS logic 100/100, agent 29 passed with 2 skipped, and both automated walkthroughs (offline and local Supabase) pass. **Voice has only run against fakes.** 35 rulings and the deferred minors are in `ios/docs/OVERNIGHT.md`. To check on the real iPad: chimes vs voice audio, turning Stage Manager off, and signing.
- **One cross-team follow-up was sent to the backend:** after the shopper says Yes to a deal, the next suggestion shouldn't wait until that item is physically in the cart.
- **CV:** done. **Backend:** done, apart from the follow-up above.
- Synced: 2 more commits pushed; no secrets.

### 2026-10-24 ~02:20 · check-in
- **iPad: milestones 1 and 2 committed.** The app runs on Supabase through `KartSupabase` (REST + realtime), with a debug panel, automated rehearsals, and a Line voice session. `agent/` has a README and a test pinning the iPad custom-event contract. Still running (verification).
- **CV:** finished its final whole-branch review, with all Critical/Important findings fixed. 80 tests pass and its end-to-end test passes 2/2. Contract v0.10 adds `resolves_event_id`. Idle and done.
- **Backend:** done, idle.
- Synced: 7 more commits pushed; no secrets.

### 2026-10-24 ~01:50 · check-in
- **CV: DONE overnight** (idle). All 13 plan tasks are done, with 62 tests passing on the Mac (synthetic two-camera scenes: hands, lighting, bumps, stacked items, a dead camera). **The end-to-end test against local Supabase passes:** the live catalog loads from `product_catalog`, adds and removes reach `carts`, an outbox retry doesn't double-add, and `reset_cart` clears the Pi's memory. It has not run on real hardware. Morning steps are in `pi/docs/OVERNIGHT.md` and `pi/README.md`, and CV still needs `ANTHROPIC_API_KEY` (until then it runs local-only).
- **iPad: building.** Milestone 1 UI is committed (design system, Kart avatar, welcome/greeting, trip panel with the next-stop map, checkout, pay overlay, receipt). It's now verifying the live-deal beat against local Supabase and planning milestone 2.
- **Backend:** done, idle.
- Synced: 10 more commits pushed; no secrets.

### 2026-10-24 ~01:20 · check-in
- **Backend: DONE overnight** (idle). Local Supabase is running through colima, with values in `.env` under the `LOCAL SUPABASE` header and no Anthropic or Cartesia keys. Also done: `go_live.sh`, which was rehearsed against local and refuses to run while `.env` points at local; the end-to-end suite (`backend/e2e`); anonymous store insights; `DEMO.md`; and `cart.py` emergency levers. Tests: 50 backend, 42 merchant, 4 end-to-end, 5 Edge Function. Its message to the other chats was blocked by the app's pause, so the manager relayed "local Supabase is up" to CV and the iPad.
- **CV: building.** Motion/settle, change detection, persistent cart memory, the few-shot gallery and the synthetic scene generator are committed; now on cloud identification.
- **iPad: building.** The backend protocol, mock cart rules, deal suggestions with P10, checkout, simulated payment, the voice protocol with a scripted mock agent, and avatar mood are committed.
- Synced: 19 commits pushed. No secrets in tracked files, and `.env` is untracked.

### 2026-10-24 ~01:00 · overnight build started
- Dylan is away until morning. All three chats are building autonomously, logging their decisions in `*/docs/OVERNIGHT.md`, and committing to `main` after each piece.
- **Backend:** bringing up a local Supabase (colima + `supabase start`) so CV and the iPad can integrate tonight with no hosted keys. Then `go_live.sh`, an end-to-end test, merchant analytics, and `DEMO.md`.
- **CV:** executing the plan milestone by milestone on the Mac (synthetic scenes, replay, fake Claude), then the HTTP sink against local Supabase.
- **iPad:** milestone 1 (screens, avatar, debug panel on the mock), then milestone 2 against local Supabase in the Simulator.
- **Hardware (teammate):** Pi setup, camera check and autostart are done (`hardware/`). Testing on the real Pi resumes in the morning.
