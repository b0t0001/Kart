import Foundation
import Testing
@testable import KartCore

@Test func qtyChangesMapToAddedAndRemoved() {
    #expect(CartDiff.changes(from: cart([]), to: cart([("barilla-spaghetti", "1.99", 1)])) == [.added(productId: "barilla-spaghetti")])
    #expect(CartDiff.changes(from: cart([("barilla-spaghetti", "1.99", 1)]), to: cart([("barilla-spaghetti", "1.99", 2)])) == [.added(productId: "barilla-spaghetti")])
    #expect(CartDiff.changes(from: cart([("barilla-spaghetti", "1.99", 1)]), to: cart([])) == [.removed(productId: "barilla-spaghetti")])
}

@Test func priceDropIsReported() {
    #expect(CartDiff.changes(from: cart([("kirkland-parmesan", "12.99", 1)]), to: cart([("kirkland-parmesan", "9.99", 1)]))
            == [.priceDropped(productId: "kirkland-parmesan", from: Decimal(string: "12.99")!, to: Decimal(string: "9.99")!)])
}

@Test func tripChangeProducesNoChanges() {
    #expect(CartDiff.changes(from: cart([("bananas", "1.49", 1)]), to: cart([], trip: tripB)).isEmpty)
}
