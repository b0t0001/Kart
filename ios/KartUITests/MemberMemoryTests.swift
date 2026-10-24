import XCTest

/// The member beat (member memory beta, spec §2), offline on the mock: sign in as Dylan, Kart's question,
/// Friendsgiving remembered, checkout, fast-forward to the day before, sign in again, and what Kart remembers.
final class MemberMemoryTests: XCTestCase {
    private var app: XCUIApplication!

    override func setUp() {
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .landscapeLeft
    }

    @MainActor
    func testMemberBeatOffline() {
        launch()
        debugToggle("debug.memberMemory")
        signIn()
        expectText("Welcome back, Dylan! Leo's soccer party is tomorrow.")
        debug("debug.say.5")                                    // "Hey Kart": the greeting gives way to shopping
        expectText("Any fun plans coming up I can help you shop for?")
        XCTAssertTrue(app.descendants(matching: .any)["foryou.card"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["member.chip"].exists)
        shot("member-1-foryou")
        debug("debug.say.6")                                    // "I'm hosting Friendsgiving next Saturday, ten people."
        expectText("Ooh, fun. I'll remember that, and I started a list for it.")

        debug("debug.add.whole-milk")
        app.buttons["checkout.button"].tap()
        app.buttons["pay.button"].tap()
        expectText("Saved to Dylan's history.", timeout: 15)
        shot("member-2-receipt")
        app.buttons["receipt.done"].tap()
        expectText("Tap to start shopping")

        debug("debug.date.beforeEvent")                         // "Day before Friendsgiving"
        XCTAssertTrue(app.descendants(matching: .any)["demo.date"].waitForExistence(timeout: 5))
        signIn()
        expectText("Friendsgiving is tomorrow")
        debug("debug.say.5")                                    // a new trip: Kart may ask again
        let shopIt = app.buttons["foryou.shopIt"]
        XCTAssertTrue(shopIt.waitForExistence(timeout: 10))
        XCTAssertTrue(shopIt.label.contains("Friendsgiving"), "Shop it is for \(shopIt.label)")
        shot("member-3-recall")

        app.buttons["member.chip"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["memory.sheet"].waitForExistence(timeout: 5))
        expectText("Leo's soccer party, pasta for the team")
        shot("member-4-memories")
    }

    @MainActor
    private func signIn() {
        app.buttons["welcome.signIn"].tap()
        for key in ["1", "0", "2", "9"] { app.buttons["member.key.\(key)"].tap() }
        XCTAssertTrue(app.buttons["member.confirm"].waitForExistence(timeout: 5))
        expectText("Dylan?")
        app.buttons["member.confirm"].tap()
    }

    @MainActor
    private func launch() {
        app?.terminate()
        app = XCUIApplication()
        app.launchArguments = ["-KartDebugButton", "YES", "-KartStill", "YES", "-KartBackend", "mock"]
        app.launch()
    }

    @MainActor
    private func debug(_ id: String) {
        app.demoControl(id).tap()
        app.buttons["debug.close"].tap()
    }

    @MainActor
    private func debugToggle(_ id: String) {
        let toggle = app.demoControl(id)
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
        Thread.sleep(forTimeInterval: 1.0)
        let directory = URL(fileURLWithPath: ProcessInfo.processInfo.environment["SHOT_DIR"] ?? NSTemporaryDirectory())
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? XCUIScreen.main.screenshot().pngRepresentation.write(to: directory.appending(path: "\(name).png"))
    }
}
