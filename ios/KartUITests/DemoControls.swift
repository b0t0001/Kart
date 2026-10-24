import XCTest

extension XCUIApplication {
    /// Opens the demo controls and scrolls until the control `id` sits fully in view below the panel's header.
    /// `exists` alone isn't enough: a row scrolled under the header exists, but a tap on it lands on the header.
    @MainActor
    func demoControl(_ id: String) -> XCUIElement {
        buttons["debug.open"].tap()
        let target = descendants(matching: .any)[id]
        let list = tables.firstMatch.exists ? tables.firstMatch : collectionViews.firstMatch
        let header: CGFloat = 70
        func inView() -> Bool {
            target.exists && target.isHittable
                && target.frame.minY > list.frame.minY + header && target.frame.maxY < list.frame.maxY - 10
        }
        var steps = 0
        while !inView() && steps < 24 {
            // Not loaded yet or below the fold: move the content up. Under the header: move it back down a little.
            let up = !target.exists || target.frame.minY > list.frame.minY + header
            let from = list.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.7 : 0.35))
            let to = list.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.4 : 0.6))
            from.press(forDuration: 0.05, thenDragTo: to, withVelocity: .slow, thenHoldForDuration: 0.1)
            steps += 1
        }
        XCTAssertTrue(inView(), "demo control \(id) not reachable")
        return target
    }
}
