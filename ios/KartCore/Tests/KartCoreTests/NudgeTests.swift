import Foundation
import Testing
@testable import KartCore

/// Quantity nudges (contract v0.12, beta): nothing changes unless `carts.features.quantity_nudges` is on.
@MainActor struct NudgeTests {
    let clock = ManualClock()

    func started(flag: Bool = true) async throws -> MockKartBackend {
        let b = MockKartBackend(catalog: try Fixtures.catalog(), clock: { [clock] in clock.now })
        if flag { try await b.setFeature("quantity_nudges", on: true) }
        try await b.startTrip()
        return b
    }
    func add(_ b: MockKartBackend, _ id: String, times: Int = 1) async {
        for _ in 0..<times { await b.simulateVision(.added, productId: id, confidence: 0.9, label: id) }
    }

    @Test func nothingChangesWithTheFlagOff() async throws {
        let b = try await started(flag: false)
        try await b.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1)])
        await add(b, "ground-beef", times: 2)
        try await b.setStatus(.checkout)
        #expect(b.cart.nudge == nil && !b.cart.quantityNudgesOn)
    }

    @Test func oneTooManyNudgesOnceAndClearsWhenPutBack() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1)])
        await add(b, "ground-beef")
        #expect(b.cart.nudge == nil)
        await add(b, "ground-beef")
        let nudge = try #require(b.cart.nudge)
        #expect(nudge.kind == .over && nudge.have == 2 && nudge.need == 1 && nudge.productId == "ground-beef")
        #expect(nudge.text == "That's your 2nd Ground Beef. Your list says 1. Keep it?")
        #expect(nudge.savings == Decimal(string: "6.99"))
        await b.simulateVision(.removed, productId: "ground-beef", confidence: 0.9, label: "b")   // put back: counts match
        #expect(b.cart.nudge == nil)
        await add(b, "ground-beef")                                     // once per product per direction per trip
        #expect(b.cart.nudge == nil)
    }

    @Test func impulseBuysAreNeverNudged() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1)])
        await add(b, "bananas", times: 3)
        #expect(b.cart.nudge == nil)
    }

    @Test func keepRaisesTheListAndOkOnlyAcknowledges() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1),
                             PlanItem(productId: "whole-milk", reason: "breakfast", qty: 1)])
        await add(b, "ground-beef", times: 2)
        try await b.dismissNudge(.keep)
        #expect(b.cart.nudge == nil && b.cart.plan.first { $0.productId == "ground-beef" }?.qty == 2)
        await add(b, "whole-milk", times: 2)                           // (no deal pairs with milk, so nothing outranks it)
        #expect(b.cart.nudge?.productId == "whole-milk")
        try await b.dismissNudge(.ok)
        #expect(b.cart.nudge == nil && b.cart.plan.first { $0.productId == "whole-milk" }?.qty == 1)
    }

    @Test func shortAtCheckoutIsOneCombinedNudge() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 2),
                             PlanItem(productId: "tostitos-salsa", reason: "tacos")])
        await add(b, "ground-beef")                                     // in Aisle 3: walking order is beef, then salsa
        try await b.setStatus(.checkout)
        let nudge = try #require(b.cart.nudge)
        #expect(nudge.kind == .under && nudge.productId == "ground-beef" && nudge.have == 1 && nudge.need == 2)
        #expect(nudge.items?.map(\.productId) == ["ground-beef", "tostitos-salsa"] && nudge.items?.last?.have == 0)
        #expect(nudge.text == "Before you go: you still need Ground Beef and Salsa.")
        try await b.dismissNudge(.shop)                                  // "Go get them": back to shopping, answered once
        #expect(b.cart.nudge == nil && b.cart.status == .shopping)
        try await b.setStatus(.checkout)
        #expect(b.cart.nudge == nil)
    }

    @Test func aPendingDealTakesPriority() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "barilla-spaghetti", reason: "pasta", qty: 1)])
        await add(b, "barilla-spaghetti", times: 2)                    // the first add offers the parmesan deal
        #expect(b.cart.suggestion != nil && b.cart.nudge == nil)
    }

    @Test func anOverNudgeWaitsForTheDealCardThenShows() async throws {
        let b = try await started()
        try await b.setPlan([PlanItem(productId: "barilla-spaghetti", reason: "pasta", qty: 1)])
        await add(b, "barilla-spaghetti", times: 2)
        #expect(b.cart.nudge == nil)                                     // the parmesan card goes first
        try await b.dismissSuggestion()
        #expect(b.cart.nudge?.productId == "barilla-spaghetti" && b.cart.nudge?.kind == .over)
    }

    @Test func cartsDecodeFeaturesNudgeAndBasis() throws {
        let json = #"{"cart_id":"7","features":{"quantity_nudges":true},"nudged":["over:ground-beef"],"#
            + #""plan":[{"product_id":"ground-beef","qty":2,"basis":"8 people x 1/4 lb = 2 lb"}],"#
            + #""nudge":{"product_id":"ground-beef","name":"Ground Beef","kind":"over","have":3,"need":2,"text":"Keep it?","savings":6.99}}"#
        let cart = try KartJSON.decoder().decode(CartState.self, from: Data(json.utf8))
        #expect(cart.quantityNudgesOn && cart.nudged == ["over:ground-beef"])
        #expect(cart.plan[0].basis == "8 people x 1/4 lb = 2 lb" && cart.nudge?.kind == .over && cart.nudge?.have == 3)
        let combined = #"{"cart_id":"7","nudge":{"product_id":"ground-beef","kind":"under","have":0,"need":1,"text":"t","#
            + #""items":[{"product_id":"ground-beef","name":"Ground Beef","have":0,"need":1,"aisle":"Aisle 3"}]}}"#
        let c = try KartJSON.decoder().decode(CartState.self, from: Data(combined.utf8))
        #expect(c.nudge?.items?.first?.aisle == "Aisle 3" && c.nudge?.items?.first?.need == 1)
        let old = try KartJSON.decoder().decode(CartState.self, from: Data(#"{"cart_id":"7"}"#.utf8))
        #expect(!old.quantityNudgesOn && old.nudge == nil && old.nudged.isEmpty)
    }

    @Test func theNudgeReachesKartInTheAgentsShape() {
        let nudge = Nudge(productId: "ground-beef", name: "Ground Beef", kind: .over, have: 2, need: 1, text: "Keep it?")
        let meta = LineCodec.metadata(.nudge(nudge))
        #expect(meta["type"] as? String == "nudge" && meta["kind"] as? String == "over")
        #expect(meta["product_id"] as? String == "ground-beef" && meta["text"] as? String == "Keep it?")
        var combined = nudge
        combined.items = [NudgeItem(productId: "ground-beef", name: "Ground Beef", have: 0, need: 1, aisle: "Aisle 3")]
        let items = LineCodec.metadata(.nudge(combined))["items"] as? [[String: Any]]
        #expect(items?.first?["product_id"] as? String == "ground-beef" && items?.first?["need"] as? Int == 1)
    }
}
