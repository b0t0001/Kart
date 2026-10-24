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
6. Your teammate pulls `main` and runs the CV code on the Pi (`pi/README.md`, `hardware/README.md`).

## Log

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
