import Foundation
import Testing
@testable import KartCore

@Test func nextStopSkipsDoneAndUnknownProducts() throws {
    var c = CartState.empty(cartId: "7")
    var done = PlanItem(productId: "barilla-spaghetti", reason: ""); done.done = true
    var soldOut = PlanItem(productId: "french-baguette", reason: ""); soldOut.inStock = false
    c.plan = [done, soldOut, PlanItem(productId: "added-after-build", reason: ""), PlanItem(productId: "rao-marinara", reason: "")]
    let s = try #require(NextStop.from(cart: c, catalog: try Fixtures.catalog()))
    #expect(s.sectionId == "A6" && s.aisleLabel == "Aisle 6" && s.shortName == "Rao's Sauce" && s.text == "Aisle 6 → Rao's Sauce")
    c.nextStep = "Aisle 6 → Rao's Sauce, $1 off"
    #expect(NextStop.from(cart: c, catalog: try Fixtures.catalog())?.text == "Aisle 6 → Rao's Sauce, $1 off")
}

@Test func hereText() throws {
    var c = CartState.empty(cartId: "7")
    #expect(NextStop.hereText(cart: c, catalog: try Fixtures.catalog()) == "Starting at the entrance")
    c.location = CartLocation(section: "A1", source: "item", at: .now)
    #expect(NextStop.hereText(cart: c, catalog: try Fixtures.catalog()) == "You're in Aisle 1 · Produce")
}
