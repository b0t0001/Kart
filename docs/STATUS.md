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
5. Run `backend/go_live.sh`; it should print PASS.
6. Your teammate pulls `main` and runs the CV code on the Pi (`pi/README.md`, `hardware/README.md`).

## Log

### 2026-10-24 ~01:00 · overnight build started
- Dylan is away until morning. All three chats are building autonomously, logging their decisions in `*/docs/OVERNIGHT.md`, and committing to `main` after each piece.
- **Backend:** bringing up a local Supabase (colima + `supabase start`) so CV and the iPad can integrate tonight with no hosted keys. Then `go_live.sh`, an end-to-end test, merchant analytics, and `DEMO.md`.
- **CV:** executing the plan milestone by milestone on the Mac (synthetic scenes, replay, fake Claude), then the HTTP sink against local Supabase.
- **iPad:** milestone 1 (screens, avatar, debug panel on the mock), then milestone 2 against local Supabase in the Simulator.
- **Hardware (teammate):** Pi setup, camera check and autostart are done (`hardware/`). Testing on the real Pi resumes in the morning.
