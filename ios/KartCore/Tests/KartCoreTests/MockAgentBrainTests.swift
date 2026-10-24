import Foundation
import Testing
@testable import KartCore

@MainActor struct MockAgentBrainTests {
    func setup() async throws -> (MockKartBackend, MockAgentBrain) {
        let b = MockKartBackend(catalog: try Fixtures.catalog()); try await b.startTrip(); return (b, MockAgentBrain(backend: b))
    }
    @Test func pastaBuildsPlan() async throws {
        let (b, brain) = try await setup()
        #expect(await brain.respond(to: "Pasta dinner for my family, four people.") == "Love it. Spaghetti, Rao's sauce, a baguette, and a Caesar kit. I'll walk you through it.")
        #expect(Set(b.cart.plan.map(\.productId)) == ["barilla-spaghetti", "rao-marinara", "french-baguette", "caesar-salad-kit"])   // the mock reorders by route
    }
    @Test func yesAcceptsSuggestion() async throws {
        let (b, brain) = try await setup()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(await brain.respond(to: "Yes") == "Done. Parmesan's on your list.")
        #expect(b.cart.plan.contains { $0.productId == "kirkland-parmesan" })
    }
    @Test func yesConfirmsPendingItemFirst() async throws {
        let (b, brain) = try await setup()
        await b.simulateVision(.added, productId: nil, confidence: 0.4, label: "jar of rao's marinara")
        #expect(await brain.respond(to: "yeah") == "Got it, Rao's Sauce.")
        #expect(b.cart.items.map(\.productId) == ["rao-marinara"] && b.events[0].resolvedAt != nil)
    }
    @Test func noDismissesSuggestion() async throws {
        let (b, brain) = try await setup()
        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
        #expect(await brain.respond(to: "No thanks") == "No problem." && b.cart.suggestion == nil)
    }
    @Test func doneStartsCheckout() async throws {
        let (b, brain) = try await setup()
        #expect(await brain.respond(to: "I'm done.") == "Here's your bill. Tap your card when you're ready.")
        #expect(b.cart.status == .checkout)
    }
    @Test func unknownAsksAgain() async throws {
        let (_, brain) = try await setup()
        #expect(await brain.respond(to: "I know a guy") == "Sorry, say that again?")   // "know" must not match "no"
    }
    @Test func reactions() async throws {
        let (b, brain) = try await setup()
        try await b.setPlan(DemoScript.pastaPlan)
        #expect(brain.react(to: .cartChanged(.added(productId: "barilla-spaghetti"))) == "Nice. Rao's is right beside it.")
        #expect(brain.react(to: .cartChanged(.added(productId: "caesar-salad-kit"))) == "Got the Caesar Kit.")
        #expect(brain.react(to: .cartChanged(.added(productId: "bananas"))) == nil)
        #expect(brain.react(to: .cartChanged(.removed(productId: "barilla-spaghetti"))) == "Took the Spaghetti off your bill.")
        #expect(brain.react(to: .cartChanged(.priceDropped(productId: "kirkland-parmesan", from: Decimal(string: "12.99")!, to: Decimal(string: "9.99")!))) == "Good news, Parmesan just dropped to $9.99.")
        #expect(brain.react(to: .suggestion(Suggestion(productId: "kirkland-parmesan", dealId: "d-parm-3off", text: "Parmesan is $3 off in Aisle 4. Want it?"))) == "Parmesan is $3 off in Aisle 4. Want it?")
    }
}
