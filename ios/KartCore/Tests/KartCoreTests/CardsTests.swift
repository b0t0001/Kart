import Foundation
import Testing
@testable import KartCore

private let fixedNow = Date(timeIntervalSince1970: 1_800_000_000)

private func ctx(cart: CartState? = nil, events: [CartEvent] = []) throws -> CardContext {
    let catalog = try Fixtures.catalog()
    var shopping = CartState.empty(cartId: "7")
    shopping.status = .shopping
    return CardContext(cart: cart ?? shopping, events: events, catalog: catalog, now: fixedNow, voiceOnline: true,
                       locallyResolved: [],
                       baselineDeals: Dictionary(uniqueKeysWithValues: catalog.deals.map { ($0.id, $0.label) }),
                       acknowledgedNewDeals: [])
}

private func unknown(id: Int64, label: String) -> CartEvent {
    CartEvent(id: id, eventId: UUID(), cartId: "7", type: .added, productId: nil, confidence: 0.4, source: .vision,
              label: label, applied: false, createdAt: fixedNow)
}

@Test func unknownEventBecomesConfirmCardWithBestGuess() throws {
    let cards = CardDeriver.cards(try ctx(events: [unknown(id: 12, label: "jar of rao's marinara")]))
    #expect(cards.first?.id == "confirm-12")
    #expect(cards.first?.title == "Is this the Rao's Sauce?")
    #expect(cards.first?.actions == [.yes, .somethingElse, .remove])
}
@Test func poorMatchAsksOpenQuestion() throws {
    let card = try #require(CardDeriver.cards(try ctx(events: [unknown(id: 3, label: "blue umbrella")])).first)
    #expect(card.title == "What did you just add?" && card.actions == [.somethingElse, .remove])
}
@Test func priorityConfirmThenOfflineThenDeal() throws {
    var c = try ctx(events: [unknown(id: 1, label: "jar of rao's marinara")])
    c.cart.suggestion = Suggestion(productId: "kirkland-parmesan", dealId: "d-parm-3off", text: "Parmesan is $3 off in Aisle 4. Want it?")
    c.voiceOnline = false
    #expect(CardDeriver.cards(c).map(\.id) == ["confirm-1", "offline", "deal-d-parm-3off"])
    #expect(CardDeriver.cards(c)[2].title == "Parmesan is $3 off in Aisle 4. Want it?")
}
@Test func locallyResolvedEventHasNoCard() throws {
    let e = unknown(id: 1, label: "jar"); var c = try ctx(events: [e]); c.locallyResolved = [e.eventId]
    #expect(CardDeriver.cards(c).isEmpty)
}
@Test func newRelevantDealGetsCardUntilAcknowledged() throws {
    var c = try ctx(); c.cart.plan = [PlanItem(productId: "bananas", reason: "breakfast")]
    c.catalog.deals.append(Deal(id: "d-bananas-50c", productId: "bananas", type: .amountOff, value: Decimal(string: "0.5")!, label: "50¢ off", pairsWith: [], endsAt: nil))
    #expect(CardDeriver.cards(c).map(\.title) == ["New deal: Bananas 50¢ off"])
    #expect(CardDeriver.cards(c).first?.actions == [.gotIt])       // already planned
    c.acknowledgedNewDeals = ["d-bananas-50c|50¢ off"]
    #expect(CardDeriver.cards(c).isEmpty)
}
@Test func irrelevantOrExpiredNewDealsAreIgnored() throws {
    var c = try ctx()
    c.catalog.deals.append(Deal(id: "d-eggs", productId: "large-eggs", type: .amountOff, value: 1, label: "$1 off", pairsWith: [], endsAt: nil))
    #expect(CardDeriver.cards(c).isEmpty)                            // nothing planned or in the cart
    c.cart.plan = [PlanItem(productId: "large-eggs", reason: "breakfast")]
    c.catalog.deals[c.catalog.deals.count - 1].endsAt = c.now.addingTimeInterval(-60)
    #expect(CardDeriver.cards(c).isEmpty)                            // expired
}
