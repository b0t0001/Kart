import XCTest

/// The demo against the live backend (hosted or local) on its own cart: every write goes through the contract's
/// RPCs and every change comes back over realtime. Run via scripts/rehearse-live.sh, which resets only this cart
/// and never the store's catalog, so the Parmesan card comes from the store's seeded deal.
final class LiveRehearsalTests: XCTestCase {
    private var app: XCUIApplication!
    private var shots: URL { URL(fileURLWithPath: ProcessInfo.processInfo.environment["SHOT_DIR"] ?? NSTemporaryDirectory()) }

    override func setUp() {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .landscapeLeft
    }

    @MainActor
    func testLiveTrip() throws {
        app = XCUIApplication()
        app.launchArguments = ["-KartDebugButton", "YES", "-KartStill", "YES", "-KartBackend", "supabase", "-KartCartID", "ipad-live"]
        app.launch()
        app.buttons["welcome.start"].tap()
        expectText("Hi, I'm Kart. What are we shopping for today?")

        debug("debug.say.0")                               // the scripted brain writes the plan through set_plan
        expectText("Love it. Spaghetti, Rao's sauce, a baguette, and a Caesar kit. I'll walk you through it.")
        debug("debug.add.barilla-spaghetti")               // apply_cart_event, as the Pi would
        expectText("$1.99")
        shot("live-1-before-deal")

        let parmesanCard = app.staticTexts.containing(NSPredicate(format: "label BEGINSWITH %@", "Parmesan is")).firstMatch
        XCTAssertTrue(parmesanCard.waitForExistence(timeout: 20), "no Parmesan deal card (is the store's Parmesan deal active?)")
        shot("live-2-deal-popped")
        app.buttons["card.Yes"].tap()
        XCTAssertTrue(app.buttons["card.No thanks"].waitForNonExistence(timeout: 5))

        debug("debug.unsure.rao-marinara")
        expectText("Is this the Rao's Sauce?")
        shot("live-3-confirm")
        app.buttons["card.Yes"].tap()
        XCTAssertTrue(app.buttons["card.Not this"].waitForNonExistence(timeout: 5))

        app.buttons["checkout.button"].tap()
        expectText("Your bill")
        shot("live-4-checkout")
        app.buttons["pay.button"].tap()
        expectText("You're all set", timeout: 15)
        shot("live-5-receipt")
        app.buttons["receipt.done"].tap()
        expectText("Tap to start shopping")
    }

    // MARK: Helpers (same as RehearsalTests)

    @MainActor
    private func debug(_ id: String) {
        app.demoControl(id).tap()
        app.buttons["debug.close"].tap()
    }

    @MainActor
    private func expectText(_ text: String, timeout: TimeInterval = 20, file: StaticString = #filePath, line: UInt = #line) {
        let found = app.staticTexts[text].waitForExistence(timeout: timeout)
            || app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", text)).firstMatch.waitForExistence(timeout: 1)
        XCTAssertTrue(found, "never saw “\(text)”", file: file, line: line)
    }

    @MainActor
    private func shot(_ name: String) {
        Thread.sleep(forTimeInterval: 1.0)                // let transitions finish before the picture
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: shots.appending(path: "\(name).png"))
    }
}
