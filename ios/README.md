# Kart: the iPad app

The cart-mounted iPad app: Kart greets the shopper, turns "pasta dinner for four" into a route, watches what goes in the cart, points out deals, and checks out with no register. Spec: [docs/specs/2026-10-24-ipad-app-design.md](docs/specs/2026-10-24-ipad-app-design.md). Plan: [docs/plans/2026-10-24-ipad-app-m1.md](docs/plans/2026-10-24-ipad-app-m1.md). Overnight notes: [docs/OVERNIGHT.md](docs/OVERNIGHT.md).

## Layout

| Path | What |
|---|---|
| `KartCore/` | Swift package with every model and rule: the contract models, `MockKartBackend` (imitates the Supabase rules), cards, the trip router, the scripted mock agent and voice, simulated payment, `AppModel`. Tested on the Mac with `swift test`. |
| `Kart/` | The SwiftUI app: design system, Kart's avatar, the five screens, the debug panel. |
| `KartUITests/` | Simulator rotation and the automated demo rehearsal. |
| `scripts/` | `shoot.sh` (scenario screenshots), `rehearse.sh` (run the demo end to end), `landscape.sh` (turn the simulator). |

## Build and test

```bash
brew install xcodegen
```
```bash
cd ios && xcodegen generate && open Kart.xcodeproj
```
```bash
cd ios/KartCore && swift test
```

`Kart.xcodeproj` is generated from `project.yml`, so regenerate it after pulling and don't commit it.

## See it

- **Scenario screenshots:** run `scripts/landscape.sh` once per simulator boot, then `scripts/shoot.sh welcome,shopping,deal,confirm,crowded,checkout,checkoutUnresolved,receipt` (also `greeting`, `avatar`). PNGs land in `build/shots/`.
- **Automated rehearsal:** `scripts/rehearse.sh` taps through the whole §1.1 demo, the live merchant beat, and the failure paths. Screenshots land in `build/shots/rehearsal/`.
- **Launch arguments:** `-KartScenario <name>` seeds a state. `-KartDebugButton YES` shows a corner button for the debug panel. `-KartStill YES` pauses Kart's ambient animation (UI tests need it).

## Run the demo by hand

On the iPad, a **three-finger long press** anywhere opens the demo controls (or tap the corner button with `-KartDebugButton YES`):

- **You say:** plays the shopper's lines into the scripted Kart ("Pasta dinner…", "Yes", "No thanks", "Taco night…", "I'm done.").
- **Cart:** Add / Add unsure / Remove any product, exactly what the Pi sends; "Add unknown thing" for an unrecognized item.
- **Merchant:** remove or create the parmesan deal (the live merchant beat), and push a bananas price drop.
- **Trip / Payment:** new trip, go to checkout, end trip, a backend-reconnecting toggle, a forced payment failure.

### Two-minute rehearsal (mock backend, no network)

1. Tap to start; Kart greets out loud.
2. "Pasta dinner…" → the list appears in walking order; next stop "Aisle 1 → Caesar Kit".
3. Add Spaghetti → chime, the list checks off, $1.99, the parmesan deal card, and Kart says it.
4. "Yes" → parmesan joins the list.
5. **Merchant beat:** start a trip after "Remove Parmesan deal"; Spaghetti then brings no deal card (the baguette deal is for something already on the list, so it stays quiet). "Create Parmesan $3 off" pops the parmesan card in, and Kart says it once.
6. "Add unsure" on Rao's → "Is this the Rao's Sauce?" → Yes.
7. Remove Spaghetti → "Took the Spaghetti off your bill.", and the total drops.
8. "I'm done." → the bill; Pay → the receipt with savings and trip time; Done → Welcome.
