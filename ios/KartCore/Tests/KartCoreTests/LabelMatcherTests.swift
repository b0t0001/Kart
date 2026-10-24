import Foundation
import Testing
@testable import KartCore

@Test func matchesRaoFromVisionLabel() throws {
    let m = LabelMatcher.matches(for: "red jar of marinara sauce", in: try Fixtures.catalog().products)
    #expect(m.first?.product.id == "rao-marinara" && (m.first?.score ?? 0) >= 0.5)
    #expect(m.count <= 3)
}
@Test func matchesSpaghettiBox() throws {
    #expect(LabelMatcher.matches(for: "box of spaghetti pasta", in: try Fixtures.catalog().products).first?.product.id == "barilla-spaghetti")
}
@Test func noMatchForStrangers() throws {
    #expect(LabelMatcher.matches(for: "blue umbrella", in: try Fixtures.catalog().products).isEmpty)
}
