import Foundation
import Testing
@testable import KartCore

@MainActor struct MockBackendDealsTests {
    let clock = ManualClock()
    func started() async throws -> MockKartBackend {
        let b = MockKartBackend(catalog: try Fixtures.catalog(), clock: { [clock] in clock.now }); try await b.startTrip(); return b
    }
    let bananaDeal = Deal(id: "d-bananas-50c", productId: "bananas", type: .amountOff, value: Decimal(string: "0.5")!, label: "50¢ off", pairsWith: [], endsAt: nil)

    @Test func addingPairedItemSuggestsDeal() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        let s = try #require(b.cart.suggestion)
        #expect(s.dealId == "d-parm-3off" && s.productId == "kirkland-parmesan")
        #expect(s.text == "Parmesan is $3 off in Aisle 4. Want it?")
        #expect(s.salePrice == Decimal(string: "9.99") && s.aisle == "Aisle 4")
        #expect(b.cart.suggestedDeals == ["d-parm-3off"])
    }
    @Test func noSuggestionWhenDealProductAlreadyPlanned() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "kirkland-parmesan", reason: "deal"),
                             PlanItem(productId: "french-baguette", reason: "pasta dinner")])
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.suggestion == nil)
    }
    @Test func dismissedDealIsNotOfferedAgainThisTrip() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        try await b.dismissSuggestion()
        #expect(b.cart.suggestion == nil)
        await b.simulateVision(.added, productId: "rao-marinara", confidence: 0.9, label: "r")
        #expect(b.cart.suggestion?.dealId == "d-baguette-1off")
        #expect(b.cart.suggestion?.text == "Baguette is $1 off in Aisle 2. Want it?")
    }
    @Test func planningSuggestedProductClearsSuggestion() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        try await b.setPlan([PlanItem(productId: "kirkland-parmesan", reason: "deal")])
        #expect(b.cart.suggestion == nil)
    }
    @Test func pushedDealDropsPriceOfItemsAlreadyInCart() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b")
        await b.pushDeal(bananaDeal)
        #expect(b.cart.items[0].price == Decimal(string: "0.99") && b.cart.items[0].dealLabel == "50¢ off")
        #expect(b.cart.savings == Decimal(string: "0.5"))
    }
    @Test func removedDealKeepsPriceForItemsAlreadyInCart() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "kirkland-parmesan", confidence: 0.9, label: "p")
        await b.removeDeal(id: "d-parm-3off")
        #expect(b.cart.items.map(\.price) == [Decimal(string: "9.99")!])
        await b.simulateVision(.added, productId: "kirkland-parmesan", confidence: 0.9, label: "p")
        #expect(b.cart.items.map(\.price) == [Decimal(string: "9.99")!] && b.cart.items[0].qty == 2)   // one line keeps the lower price
        #expect(b.cart.total == Decimal(string: "19.98"))
    }
    @Test func storeCreatedDealReplacesCurrentSuggestion() async throws {
        let b = try await started()
        await b.removeDeal(id: "d-parm-3off")
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.suggestion?.dealId == "d-baguette-1off")
        clock.now += 30
        await b.pushDeal(Deal(id: "d-parm-3off", productId: "kirkland-parmesan", type: .amountOff, value: 3, label: "$3 off",
                              pairsWith: ["barilla-spaghetti", "rao-marinara"], endsAt: nil))
        #expect(b.cart.suggestion?.dealId == "d-parm-3off" && b.cart.suggestion?.offeredAt == clock.now)
        #expect(b.cart.suggestion?.text == "Parmesan is $3 off in Aisle 4. Want it?")
        #expect(b.cart.suggestedDeals == ["d-baguette-1off", "d-parm-3off"])
    }
    @Test func checkoutBlockedByUnresolvedItems() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: nil, confidence: 0.3, label: "jar")
        await #expect(throws: KartBackendError.unresolvedItems(count: 1)) { _ = try await b.checkout(provider: "simulated") }
    }
    @Test func checkoutReturnsReceiptAndMarksPaid() async throws {
        let b = try await started()
        await b.simulateVision(.added, productId: "kirkland-parmesan", confidence: 0.9, label: "p")
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        clock.now += 1380
        let r = try await b.checkout(provider: "simulated")
        #expect(r.total == Decimal(string: "11.98") && r.savings == 3 && r.itemCount == 2 && r.durationS == 1380)
        #expect(r.provider == "simulated" && r.status == "paid" && r.items.count == 2 && r.tripId == b.cart.tripId)
        #expect(b.cart.status == .paid)
        #expect(try await b.checkout(provider: "simulated") == r)          // idempotent per trip
        await #expect(throws: KartBackendError.invalidStatus) { try await b.setStatus(.paid) }
        try await b.endTrip(); #expect(b.cart.status == .idle)
    }
}

@MainActor @Test func receiptIsExposedForTheTripOnly() async throws {
    let b = MockKartBackend(catalog: try Fixtures.catalog()); try await b.startTrip()
    #expect(b.receipt == nil)
    await b.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b")
    let r = try await b.checkout(provider: "simulated")
    #expect(b.receipt == r)
    try await b.startTrip()
    #expect(b.receipt == nil)
}

@Test func reactionEventsRememberWhenTheyHappened() {
    let at = Date(timeIntervalSince1970: 1_800_000_000)
    #expect(ReactionEvent(reaction: .wave, at: at).at == at)
}
