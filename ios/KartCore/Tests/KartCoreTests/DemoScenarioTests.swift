import Foundation
import Testing
@testable import KartCore

@MainActor @Test func scenariosSeedExpectedStates() async throws {
    func run(_ s: DemoScenario) async throws -> MockKartBackend {
        let clock = ManualClock()
        let b = MockKartBackend(catalog: try Fixtures.catalog(), clock: { clock.now }); try await s.apply(to: b, clock: clock); return b }
    #expect(try await run(.welcome).cart.status == .idle)
    #expect(try await run(.greeting).transcript.map(\.text) == [DemoScript.greeting])
    let shop = try await run(.shopping)
    #expect(shop.cart.items.count == 2 && shop.cart.plan.count == 4 && shop.cart.suggestion == nil)
    #expect(try await run(.deal).cart.suggestion?.dealId == "d-parm-3off")
    #expect(try await run(.confirm).events.contains { $0.needsConfirmation })
    #expect(try await run(.crowded).cart.items.count == 12)
    #expect(try await run(.checkoutUnresolved).cart.status == .checkout)
    #expect(try await run(.receipt).cart.status == .paid)
}
