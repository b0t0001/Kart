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
        expectText("Welcome back, Dylan!")
        debug("debug.say.5")                                    // "Hey Kart": the greeting gives way to shopping
        expectText("Any fun plans coming up I can help you shop for?")
        XCTAssertTrue(app.descendants(matching: .any)["foryou.card"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["member.chip"].exists)
        shot("member-1-foryou")

        // Act 1: memory, made live.
        debug("debug.say.6")                                    // "Oh, next Saturday is Leo's soccer team party, …"
        expectText("Got it, I'll remember Leo's party on Saturday. Want me to save a list for it?")
        debug("debug.say.1")                                    // "Yes"
        expectText("Saved: three boxes of spaghetti and two jars of marinara for Leo's soccer team party.")
        shot("member-2-saved")

        // Act 2: the fast-forward, a new trip, and Kart remembers.
        debug("debug.date.beforeEvent")                         // "Fast-forward to <day before> (day before Leo's …)"
        expectText("Tap to start shopping")
        XCTAssertTrue(app.descendants(matching: .any)["demo.date"].waitForExistence(timeout: 5))
        signIn()
        expectText("Leo's soccer team party is tomorrow. Want the list you saved?")
        shot("member-3-recall")
        debug("debug.say.1")                                    // "Yes"
        expectText("Done, it's on your list.")
        expectText("Spaghetti")

        app.buttons["member.chip"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["memory.sheet"].waitForExistence(timeout: 5))
        expectText("Leo's soccer team party, pasta for 12")
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
