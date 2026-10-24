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
