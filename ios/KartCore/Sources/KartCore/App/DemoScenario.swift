import Foundation

/// Seeded states for screenshots, rehearsal, and the offline demo (launch with `-KartScenario <name>`).
/// Nothing is spoken: transcript lines are written directly.
public enum DemoScenario: String, CaseIterable, Sendable {
    case welcome, greeting, shopping, deal, confirm, crowded, checkout, checkoutUnresolved, receipt

    static let unsureLabel = "red jar of Rao's marinara"
    static let crowdedProducts = [
        "avocados", "mission-tortillas", "ground-beef", "tillamook-mexican-cheese", "tostitos-salsa", "taco-seasoning",
        "tostitos-chips", "daisy-sour-cream", "bananas", "whole-milk", "large-eggs", "kirkland-paper-towels",
    ]
    static let crowdedTwice: Set<String> = ["avocados", "tostitos-salsa", "bananas"]
    static let checkoutProducts = ["kirkland-parmesan", "barilla-spaghetti", "rao-marinara", "french-baguette"]

    /// `clock` must be the clock `backend` was built with.
    @MainActor public func apply(to backend: MockKartBackend, clock: ManualClock) async throws {
        guard self != .welcome else { return }
        try await backend.startTrip()
        try await backend.appendTranscript(.agent, DemoScript.greeting)
        switch self {
        case .welcome, .greeting:
            return
        case .shopping, .deal, .confirm:
            try await Self.pastaTrip(backend)
            if self != .deal { try await backend.dismissSuggestion() }
            if self == .confirm {
                await backend.simulateVision(.added, productId: nil, confidence: 0.42, label: Self.unsureLabel)
            }
        case .crowded:
            try await backend.appendTranscript(.user, "Taco night for eight.")
            try await backend.appendTranscript(.agent, "Taco night it is. Six things on your list, starting with the closest.")
            try await backend.setPlan(DemoScript.tacoPlan)
            for id in Self.crowdedProducts {
                await backend.simulateVision(.added, productId: id, confidence: 0.95, label: id)
                if Self.crowdedTwice.contains(id) { await backend.simulateVision(.added, productId: id, confidence: 0.95, label: id) }
            }
            try await backend.dismissSuggestion()
        case .checkout, .checkoutUnresolved, .receipt:
            for id in Self.checkoutProducts { await backend.simulateVision(.added, productId: id, confidence: 0.95, label: id) }
            try await backend.dismissSuggestion()
            if self == .checkoutUnresolved {
                await backend.simulateVision(.added, productId: nil, confidence: 0.42, label: Self.unsureLabel)
            }
            try await backend.setStatus(.checkout)
            if self == .receipt {
                clock.now += 1380
                _ = try await backend.checkout(provider: "simulated")
            }
        }
    }

    private static func pastaTrip(_ backend: MockKartBackend) async throws {
        try await backend.appendTranscript(.user, DemoScript.userLines[0])
        try await backend.appendTranscript(.agent, "Love it. Spaghetti, Rao's sauce, a baguette, and a Caesar kit. I'll walk you through it.")
        try await backend.setPlan(DemoScript.pastaPlan)
        await backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.95, label: "spaghetti")
        await backend.simulateVision(.added, productId: "bananas", confidence: 0.95, label: "bananas")
    }
}
