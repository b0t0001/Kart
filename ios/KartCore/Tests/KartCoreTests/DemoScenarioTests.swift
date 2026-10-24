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
    let amounts = try await run(.amounts)                     // taco night for eight: 2 lb beef, one in the cart
    #expect(amounts.cart.plan.first { $0.productId == "ground-beef" }.map { ($0.qty, $0.done) } ?? (0, true) == (2, false))
    let short = try await run(.checkoutShort)                 // beta on: one pound of beef short at checkout
    #expect(short.cart.status == .checkout && short.cart.nudge?.kind == .under)
    let nudged = try await run(.nudge)                        // beta on: one too many ground beef
    #expect(nudged.cart.quantityNudgesOn && nudged.cart.nudge?.kind == .over)
    let talk = try await run(.talkative)                     // the on-device taco test: long captions plus a deal card
    #expect(talk.transcript.count == 3 && talk.transcript[1].text.count > 150 && talk.cart.suggestion != nil)
    #expect(try await run(.checkoutUnresolved).cart.status == .checkout)
    #expect(try await run(.receipt).cart.status == .paid)
}
