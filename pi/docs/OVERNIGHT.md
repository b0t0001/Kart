# CV overnight build: morning notes for Dylan

Built 2026-10-24 overnight, hands-off, from the plan you approved through the manager
(`pi/docs/plans/2026-10-24-cv-pipeline.md`). Everything is in `pi/` and `tools/`, committed on `main`
in 25 CV commits. The manager pushes `main` to GitHub (it had already pushed these by the end of the night).

## Where it stands

- **All 13 plan tasks are built, a fresh-eyes review ran, and every Critical and Important finding is
  fixed.** 80 tests pass on the Mac with no camera, network or API key
  (`pi/.venv/bin/python -m pytest pi/tests -q`). They drive the real pipeline with synthetic two-camera
  scenes covering:
  - adds and removes;
  - a hand that passes, rests, lingers after placing, pauses while grabbing, or hovers;
  - a hand with no visible arm, and a strap left over the rim;
  - lighting and white-balance drift, soft shadows, camera wobble and bumps;
  - nudged and stacked items, two items at once, an item one camera can't see;
  - a camera dropping out and coming back, restarts, and resets.
- **End-to-end against the backend's local Supabase passes** (2 opt-in tests,
  `KART_E2E=1 pi/.venv/bin/python -m pytest pi/tests/test_e2e_supabase.py -q`):
  - The live catalog comes from the `product_catalog` view.
  - A replayed add, add, remove lands in the `carts` row with the right quantities and total.
  - Re-sending an already-applied event (an outbox retry) does **not** double-add.
  - `reset_cart` → new `trip_id` → the Pi clears its memory.
  - An unknown item that leaves gets its "Is this…?" card **resolved** in `cart_events`.

  The tests use throwaway cart ids (`cv-e2e-…`), never the demo cart `7`. A few empty test cart rows
  are left in the local DB.
- **Not verified on real hardware.** Per the manager, no SSH to the Pi tonight. Your teammate's run
  steps are in [`pi/README.md`](../README.md) under "Milestone checks".
- **Mac camera:** macOS doesn't let this background process use the camera. The live smoke test only
  showed the loop runs, retries the camera every 5 s, and exits cleanly.
- **Speed (Mac):** an idle tick takes ~2 ms, a settle ~70 ms, and an ONNX embedding ~3 ms per crop.
  Even 10× slower on the Pi 4 fits the 10 Hz loop.

## What you (or your teammate) do in the morning

1. On the Pi: `git pull` (or `hardware/sync_pi.sh`), `~/venv/bin/python tools/fetch_model.py`,
   `cp pi/config.example.json pi/config.json`.
2. Put the shared `.env` at `~/kart/.env` and **add `ANTHROPIC_API_KEY`** (on the Mac too). It's the
   one key CV still needs; without it the cart runs local-only.
3. Line the cart floor with a solid mat or cardboard, empty the cart, and walk the milestone checks in
   `pi/README.md`.
4. Enroll the props (`tools/enroll.py <product-id>`, ~1 min each), then run `tools/gallery_check.py`.
   It says whether the color histogram (the default) or the ONNX model separates the real props better.
5. Record a few real clips (`tools/record.py`): hand resting, stacking, a big colored item. They'll
   show whether white balance needs locking (README has the `v4l2-ctl` command) and become regression
   tests.

**For the demo itself:**
- Drop items and pull the hand out.
- Keep the debug view off.
- If an "Is this…?" card appears, resolve it on the iPad before checkout.

## What the review caught (all fixed, each with a test that failed first)

| # | Problem | Fix |
|---|---|---|
| C1 | A hand resting in the basket ≥ 1 s was billed as an unknown item. Grabbing an item and pausing could leave it on the bill. The synthetic hand had been invisible to the detector, so tests couldn't see it | The fake hand is now visible, with a sleeve. Changes that reach the frame edge (arms, straps) are ignored, with the old picture kept under them. Removals are matched by place. Removing an unknown clears its card (`p_resolves_event_id`) |
| C2 | A camera that dropped out and came back re-billed whatever went in meanwhile | It sits out one settle and re-syncs |
| C3 | The Pi's default matcher (ONNX) had never been run end to end; it finds unrelated items too similar | Default is now the validated color histogram; `tools/gallery_check.py` decides on real props; the stacked-item check is relative |
| I1 | A camera without an empty-basket picture turned removals into unknown adds | Its changes are ignored until a reset |
| I2 | Auto white balance shifts after reset misread removals | Per-channel color matching; the empty picture refreshes while the cart is empty |
| I3 | Some network errors killed the event-sending and trip-watching threads | Every error is a retry; the threads can't die |
| I4 | Full-frame color matching ran once per blob (slow on a Pi) | Once per camera |
| I5 | The 3 s Claude timeout was too tight over a phone hotspot | 6 s, with at most 2 crops |
| I6 | A crash between saving memory and queuing the event could lose the bill | The event is queued first |

## Decisions I made on your behalf (each is reversible)

**Setup**
- Built on `main` in the shared checkout, committing only `pi/` and `tools/`, per CONTRACT §7. *Cost if
  wrong:* the commits would need moving to a branch; cheap, since nothing is pushed.
- Ran it inline (no per-task reviewer) because you were hands-off, with one fresh whole-branch review
  at the end. *Cost if wrong:* the review found 9 issues, all fixed below.
- The live catalog reads the `product_catalog` view (active products only), per the manager's fix.
  *Cost if wrong:* one URL.
- Pinned OpenCV below 5 on the Mac, to match the Pi's 4.10. *Cost if wrong:* none.

**During the build**
- `tools/snap.py` waits out the camera's ~3 s exposure warm-up instead of skipping 10 frames.
  *Cost if wrong:* snap takes 3 s longer.
- Recordings load frames lazily; a 30 s recording would be about 1.6 GB in memory. *Cost if wrong:* none.
- Motion detection compares color, not grayscale: skin on a tan mat can have the same brightness.
  *Cost if wrong:* slightly more CPU, which is trivial.
- Claude error texts ("error: timeout" and similar) never reach the iPad; the local best guess is shown
  instead. *Cost if wrong:* less debug info in event labels (it's still in the logs).
- Test sprites use one hue each. Two of them shared a palette, which made the matcher correctly refuse.
  *Cost if wrong:* none (test fixture only).
- Fingerprints come from the tight changed region, not the padded crop. A stacked item's border showed
  the grocery underneath, dropping its match from 0.94 to 0.56. Claude and saved photos keep the padded
  crop. *Cost if wrong:* slightly less context in the fingerprint.
- An unknown add that looks just like an item that left in the same second counts as a move.
  *Cost if wrong:* a real look-alike swapped in that same second is missed.
- Added a test for the outbox's background thread. *Cost if wrong:* none.
- Resets use whichever cameras are up; a late camera takes its empty picture when it appears, if the
  cart is still empty. *Cost if wrong:* a camera first seen while items are inside is ignored until the
  next reset.
- `Pipeline.last_decisions` exists for enrollment. *Cost if wrong:* none.
- `--config` and `--state` work after the subcommand too. *Cost if wrong:* none.
- The control server is open on the hotspot (port 8080, no auth on `/reset`); the debug view is off by
  default. *Cost if wrong:* anyone on that Wi-Fi can trigger an empty-cart reset.
- Enrollment stores the tight crops. *Cost if wrong:* none.
- The log prints `MOTION` and `SETTLED` for the milestone-2 check. *Cost if wrong:* two log lines per item.

**From the review**
- A strong color cast now counts as "no change" rather than "disturbed". Either way nothing is billed.
  *Cost if wrong:* none.
- White-balance lock is documented in the README, not coded, because the Brio's control names can't be
  checked without the camera. *Cost if wrong:* more "lighting" warnings until it's applied.
- Claude gets a 6 s timeout with 2 crops (the spec said 3 s). *Cost if wrong:* an unknown item can take
  up to 6 s to show.
- Hands are handled by the edge rule instead of holding back unknown adds: no timers, nothing ever
  stalls. *Cost if wrong:* an item that itself reaches the frame edge is ignored by that camera, but the
  other camera still bills it.
- Events gain an optional `resolves_event_id`. This is additive to the contract; the RPC already accepts
  it. *Cost if wrong:* one extra null field.
- The default matcher is the color histogram; ONNX waits for `tools/gallery_check.py` on real props.
  *Cost if wrong:* look-alike colored props go to Claude more often.
- The unknown-move pairing keeps an absolute threshold (there's no runner-up to compare with).
  *Cost if wrong:* with ONNX switched on, an unknown arrival plus a departure in the same second could
  read as a move.

**Review items I set aside** (each judged and kept as is)
- How the iPad shows a removed unknown: that's iPad scope, and the card is now resolved.
- Hardware lane setup and the Python 3.13 runtime: owned by the hardware chat.
- Two items each seen by only one camera, or identical items touching: known limits in spec §5.4.
- Items dropped while the cart rolls under changing light may be missed (spec §10). With a floor
  liner, rolling alone doesn't trigger it.
- Floor map, crop upload, prices, LCD: deferred by the spec.
- Debug-page HTML: local only, and labels are escaped.
- Mac camera permission: an environment issue, not code.
- The reviewer didn't run the end-to-end test: I did, before and after the fixes.

## Deferred minors (not fixed; pick up any time)

- `/status` never reports "identifying", and shows camera timestamps rather than a healthy flag.
- A reset leaves stale reference pictures for cameras missing at that moment.
- `pi/gallery/index.npz` is keyed on file times, so committing it churns. Gitignore it.
- Enrollment accepts any added blob, so a lingering armless hand could be enrolled.
- A failing camera read spins without sleeping for up to 2 s before reopening.
- The README should mention that `/reset` is unauthenticated on the hotspot.
- `Pipeline.catalog` is set from outside the class by `main.build()`.
- The README says the model is ~9 MB, `fetch_model.py` says ~14 MB (it's 8.8 MB).
