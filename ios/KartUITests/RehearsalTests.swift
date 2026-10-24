import XCTest

/// The spec §1.1 demo, driven through the debug panel the way a teammate would run it, with screenshots.
/// Launches with `-KartStill YES` so Kart's ambient animation pauses and XCUITest can see the app idle.
final class RehearsalTests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .landscapeLeft
    }

    @MainActor
    func testPastaDemo() {
        launch()
        app.buttons["welcome.start"].tap()
        expectText("Hi, I'm Kart. What are we shopping for today?")

        debug("debug.say.0")
        expectText("Love it. Spaghetti, Rao's sauce, a baguette, and a Caesar kit. I'll walk you through it.")
        expectText("Aisle 1 → Caesar Kit")
        shot("rehearsal-1-plan")

        debug("debug.add.barilla-spaghetti")
        expectText("Parmesan is $3 off in Aisle 4. Want it?")
        shot("rehearsal-2-deal")
        app.buttons["card.Yes"].tap()
        XCTAssertTrue(app.buttons["card.No thanks"].waitForNonExistence(timeout: 5))   // the card leaves (the caption stays)
        expectText("Parmesan")                                 // joined the list

        debug("debug.unsure.rao-marinara")
        expectText("Is this the Rao's Sauce?")
        shot("rehearsal-3-confirm")
        app.buttons["card.Yes"].tap()
        XCTAssertTrue(app.buttons["card.Not this"].waitForNonExistence(timeout: 5))

        debug("debug.remove.barilla-spaghetti")
        expectText("Took the Spaghetti off your bill.", timeout: 40)

        app.buttons["checkout.button"].tap()
        expectText("Your bill")
        shot("rehearsal-4-checkout")
        app.buttons["pay.button"].tap()
        expectText("You're all set", timeout: 15)
        shot("rehearsal-5-receipt")
        app.buttons["receipt.done"].tap()
        expectText("Tap to start shopping")
    }

    @MainActor
    func testLiveMerchantBeat() {
        launch()
        debug("debug.removeParmDeal")                  // the pitch starts without the parmesan deal
        app.buttons["welcome.start"].tap()
        expectText("Hi, I'm Kart. What are we shopping for today?")
        debug("debug.say.0")
        debug("debug.add.barilla-spaghetti")
        expectText("Nice. Rao's is right beside it.", timeout: 30)
        XCTAssertFalse(app.staticTexts["Parmesan is $3 off in Aisle 4. Want it?"].exists)   // no parmesan deal yet
        shot("merchant-1-before")
        debug("debug.createParmDeal")                  // the owner creates it live
        expectText("Parmesan is $3 off in Aisle 4. Want it?", timeout: 5)
        shot("merchant-2-after")

        debug("debug.add.bananas")
        debug("debug.pushBananas")
        expectText("Bananas just dropped $0.50. You saved.", timeout: 5)
        shot("merchant-3-pricedrop")
    }

    @MainActor
    func testFailurePaths() {
        launch(["-KartScenario", "checkout"])
        debugToggle("debug.forceFailure")
        app.buttons["pay.button"].tap()
        expectText("Payment didn't go through. Try again.", timeout: 10)
        shot("failure-1-payment")
        debugToggle("debug.forceFailure")
        app.buttons["Try again"].tap()
        expectText("You're all set", timeout: 15)

        launch(["-KartScenario", "shopping"])
        debugToggle("debug.voiceOffline")
        expectText("Voice is offline. Tap to retry.")
        shot("failure-2-voice-offline")
        debugToggle("debug.voiceOffline")
        XCTAssertTrue(app.staticTexts["Voice is offline. Tap to retry."].waitForNonExistence(timeout: 5))
    }

    // MARK: Helpers

    @MainActor
    private func launch(_ extra: [String] = []) {
        app?.terminate()
        app = XCUIApplication()
        app.launchArguments = ["-KartDebugButton", "YES", "-KartStill", "YES", "-KartBackend", "mock"] + extra
        app.launch()
    }

    @MainActor
    private func openPanel(find id: String) -> XCUIElement {
        app.buttons["debug.open"].tap()
        let target = app.descendants(matching: .any)[id]
        var swipes = 0
        while !target.exists && swipes < 12 {
            app.tables.firstMatch.exists ? app.tables.firstMatch.swipeUp() : app.collectionViews.firstMatch.swipeUp()
            swipes += 1
        }
        XCTAssertTrue(target.waitForExistence(timeout: 3), "debug control \(id) not found")
        return target
    }

    @MainActor
    private func debug(_ id: String) {
        openPanel(find: id).tap()
        app.buttons["debug.close"].tap()
    }

    @MainActor
    private func debugToggle(_ id: String) {
        let toggle = openPanel(find: id)
        (toggle.switches.firstMatch.exists ? toggle.switches.firstMatch : toggle).tap()
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
        let directory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["SHOT_DIR"] ?? NSTemporaryDirectory())
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: directory.appending(path: "\(name).png"))
    }
}
