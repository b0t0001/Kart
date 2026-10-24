import Foundation

/// A scripted stand-in for the Line agent: keyword replies plus the same backend calls the real agent makes.
@MainActor public final class MockAgentBrain {
    private let backend: any KartBackend
    private static let yesWords: Set<String> = ["yes", "yeah", "yep", "sure", "ok", "okay"]
    private static let noWords: Set<String> = ["no", "nope", "nah"]

    public init(backend: any KartBackend) {
        self.backend = backend
    }

    public func respond(to utterance: String) async -> String {
        let text = Self.normalize(utterance)
        let words = Set(text.split(separator: " ").map(String.init))

        if words.contains("done") || words.contains("checkout") || text.contains("check out") || text.contains("thats everything") {
            try? await backend.setStatus(.checkout)
            return "Here's your bill. Tap your card when you're ready."
        }
        if words.contains("pasta") {
            try? await backend.setPlan(DemoScript.pastaPlan)
            return "Love it. Spaghetti, marinara, garlic bread, and a Caesar kit. I'll walk you through it."
        }
        if words.contains("taco") || words.contains("tacos") {
            try? await backend.setPlan(DemoScript.tacoPlan)
            return "Taco night it is. Six things on your list, starting with the closest."
        }
        if !words.isDisjoint(with: Self.yesWords) {
            if let event = backend.events.first(where: \.needsConfirmation),
               let best = LabelMatcher.matches(for: event.label ?? "", in: backend.catalog.products).first,
               best.score >= CardDeriver.confidentMatch {
                try? await backend.applyManualEvent(.added, productId: best.product.id, resolving: event.eventId)
                return "Got it, \(best.product.shortName)."
            }
            if let suggestion = backend.cart.suggestion {
                try? await backend.setPlan(backend.cart.plan + [PlanItem(productId: suggestion.productId, reason: "deal")])
                return "Done. \(shortName(suggestion.productId, fallback: suggestion.name))'s on your list."
            }
            return "Okay."
        }
        if !words.isDisjoint(with: Self.noWords) {
            if backend.cart.suggestion != nil {
                try? await backend.dismissSuggestion()
                return "No problem."
            }
            return "Okay."
        }
        return "Sorry, say that again?"
    }

    public func react(to event: VoiceEvent) -> String? {
        switch event {
        case .cartChanged(.added(let productId)):
            if productId == "barilla-spaghetti" { return "Nice. The marinara is right beside it." }
            guard backend.cart.plan.contains(where: { $0.productId == productId }) else { return nil }
            return "Got the \(shortName(productId))."
        case .cartChanged(.removed(let productId)):
            return "Took the \(shortName(productId)) off your bill."
        case .cartChanged(.priceDropped(let productId, _, let to)):
            return "Good news, \(shortName(productId)) just dropped to \(Money.format(to))."
        case .suggestion(let suggestion):
            return suggestion.text
        case .nudge(let nudge):
            return nudge.text
        case .dealChanged(let deal):
            return "Heads up, \(shortName(deal.productId)) just went \(deal.label)."
        case .tripContext, .cardResponse, .uiAction, .lull, .memberForgotten, .memberIdle:
            return nil
        }
    }

    private func shortName(_ productId: String, fallback: String? = nil) -> String {
        backend.catalog.product(productId)?.shortName ?? fallback ?? "That"
    }

    static func normalize(_ text: String) -> String {
        let lowered = text.lowercased().replacingOccurrences(of: "'", with: "").replacingOccurrences(of: "’", with: "")
        let spaced = lowered.map { $0.isLetter || $0.isNumber ? $0 : " " }
        return String(spaced).split(separator: " ").joined(separator: " ")
    }
}
