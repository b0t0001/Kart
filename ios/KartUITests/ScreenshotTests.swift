import XCTest

/// Turns the simulator to landscape (the app is landscape-only). Kart's face animates continuously,
/// so XCUITest never sees the app idle; screenshots are taken with simctl instead (scripts/shoot.sh).
final class OrientationTests: XCTestCase {
    @MainActor
    func testRotateToLandscape() {
        XCUIDevice.shared.orientation = .landscapeLeft
    }
}
