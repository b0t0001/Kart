import Foundation
import Testing
@testable import KartCore

@MainActor struct MockBackendCartTests {
    let clock = ManualClock()
    func backend() throws -> MockKartBackend { MockKartBackend(catalog: try Fixtures.catalog(), clock: { [clock] in clock.now }) }

    @Test func startTripResetsAndStartsShopping() async throws {
        let b = try backend(); try await b.startTrip()
        #expect(b.cart.status == .shopping && b.cart.tripId != nil && b.cart.items.isEmpty)
        #expect(b.cart.tripStartedAt == clock.now)
    }
    @Test func addingProductWithoutDealUsesListPrice() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.95, label: "spaghetti")
        #expect(b.cart.items.map(\.price) == [Decimal(string: "1.99")!])
        #expect(b.cart.total == Decimal(string: "1.99") && b.cart.savings == 0)
        #expect(b.cart.location?.section == "A6" && b.events.count == 1)
    }
    @Test func addingDealProductAppliesDeal() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: "kirkland-parmesan", confidence: 0.9, label: "parmesan")
        let line = try #require(b.cart.items.first)
        let sale = try Fixtures.salePrice("d-parm-3off"), list = try Fixtures.listPrice("kirkland-parmesan")
        let label = try Fixtures.catalog().deals.first { $0.id == "d-parm-3off" }?.label
        let saved = try Fixtures.dealValue("d-parm-3off")
        #expect(line.price == sale && line.listPrice == list)
        #expect(line.dealLabel == label && b.cart.savings == saved)
    }
    @Test func percentDealRoundsToCents() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: "daisy-sour-cream", confidence: 0.9, label: "sour cream")
        #expect(b.cart.items.first?.price == Decimal(string: "2.39"))
    }
    @Test func secondUnitIncrementsQty() async throws {
        let b = try backend(); try await b.startTrip()
        for _ in 0..<2 { await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "spaghetti") }
        #expect(b.cart.items.count == 1 && b.cart.items[0].qty == 2 && b.cart.total == Decimal(string: "3.98"))
    }
    @Test func removeDecrementsThenDrops() async throws {
        let b = try backend(); try await b.startTrip()
        for _ in 0..<2 { await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s") }
        await b.simulateVision(.removed, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.items[0].qty == 1)
        await b.simulateVision(.removed, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.items.isEmpty && b.cart.total == 0)
    }
    @Test func removingAbsentProductIsNoOp() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.removed, productId: "bananas", confidence: 0.9, label: "bananas")
        #expect(b.cart.items.isEmpty && b.cart.total == 0 && b.events.count == 1)
    }
    @Test func unknownVisionEventOnlyRecords() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: nil, confidence: 0.4, label: "red jar of rao's marinara")
        #expect(b.cart.items.isEmpty && b.events.first?.needsConfirmation == true)
    }
    @Test func planIsFilledRoutedAndTracked() async throws {
        let b = try backend(); try await b.startTrip()
        try await b.setPlan(["barilla-spaghetti", "rao-marinara", "kirkland-parmesan"].map { PlanItem(productId: $0, reason: "pasta dinner") })
        // From the entrance (x 0): Aisle 4 (8.5) is nearest, then Aisle 6 (12.5) in sent order.
        #expect(b.cart.plan.map(\.productId) == ["kirkland-parmesan", "barilla-spaghetti", "rao-marinara"])
        #expect(b.cart.plan[0].aisle == "Aisle 4" && b.cart.plan[0].inStock == true && b.cart.plan[0].dealLabel == "$1 off")
        #expect(b.cart.nextStep == "Aisle 4 → Parmesan, $1 off")
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.plan.map(\.productId) == ["barilla-spaghetti", "rao-marinara", "kirkland-parmesan"])
        #expect(b.cart.plan[0].done && b.cart.nextStep == "Aisle 6 → Marinara")
        await b.simulateVision(.added, productId: "rao-marinara", confidence: 0.9, label: "r")
        #expect(b.cart.nextStep == "Aisle 4 → Parmesan, $1 off")
        await b.simulateVision(.added, productId: "kirkland-parmesan", confidence: 0.9, label: "p")
        #expect(b.cart.nextStep == "All done → Checkout")
    }
    @Test func planQtyMustBeMet() async throws {
        let b = try backend(); try await b.startTrip()
        try await b.setPlan([PlanItem(productId: "barilla-spaghetti", reason: "pasta dinner", qty: 2)])
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(!b.cart.plan[0].done)
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(b.cart.plan[0].done)
    }
    @Test func manualEventResolvesUnknown() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: nil, confidence: 0.4, label: "jar")
        #expect(b.events[0].applied == false && b.events[0].tripId == b.cart.tripId)
        try await b.applyManualEvent(.added, productId: "rao-marinara", resolving: b.events[0].eventId)
        #expect(b.events[0].resolvedAt != nil && b.events[1].source == .manual)
        #expect(b.cart.items.map(\.productId) == ["rao-marinara"])
    }
    @Test func resolveUnknownLeavesCartAlone() async throws {
        let b = try backend(); try await b.startTrip()
        await b.simulateVision(.added, productId: nil, confidence: 0.4, label: "umbrella")
        try await b.resolveUnknown(eventId: b.events[0].eventId)
        #expect(b.events[0].resolvedAt != nil && b.cart.items.isEmpty)
    }
}
