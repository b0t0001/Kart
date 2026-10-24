import Foundation

/// A scripted stand-in for the Line agent: keyword replies plus the same backend calls the real agent makes.
@MainActor public final class MockAgentBrain {
    private let backend: any KartBackend
    private static let yesWords: Set<String> = ["yes", "yeah", "yep", "sure", "ok", "okay"]
    private static let noWords: Set<String> = ["no", "nope", "nah"]

    /// Member memory beta: the trip Kart already asked its one question on, and the event waiting for its list.
    private var askedOnTrip: UUID?
    private var listFor: Int?

    public init(backend: any KartBackend) {
        self.backend = backend
    }

    /// The first thing Kart says: a member hears their name and the event coming up.
    public func greeting() -> String {
        guard backend.cart.memberId != nil, let profile = backend.memberProfile else { return DemoScript.greeting }
        let welcome = profile.member.name.map { "Welcome back, \($0)!" }
            ?? (profile.member.trips == 0 && profile.memories.isEmpty ? "Nice to meet you!" : "Welcome back!")
        if let event = savedEvent(profile), let days = event.daysUntil, (0...2).contains(days) {
            let when = days == 0 ? "today" : days == 1 ? "tomorrow" : "in 2 days"
            return "\(welcome) \(event.title) is \(when). Want the list you saved?"
        }
        return "\(welcome) What are we shopping for today?"
    }

    private func savedEvent(_ profile: MemberProfile) -> MemberMemory? {
        let listed = Set(backend.cart.plan.map(\.productId))
        return profile.memories.first { m in
            m.kind == "event" && m.isUpcoming && (m.items ?? []).contains { !listed.contains($0.productId) }
        }
    }

    public func respond(to utterance: String) async -> String {
        let text = Self.normalize(utterance)
        let words = Set(text.split(separator: " ").map(String.init))

        if let profile = backend.memberProfile, backend.cart.memberId != nil {
            if ["hey kart", "hi kart", "hey cart", "hello kart"].contains(text), askedOnTrip != backend.cart.tripId {
                askedOnTrip = backend.cart.tripId
                return "Any fun plans coming up I can help you shop for?"
            }
            if words.contains("leos") && words.contains("party"), let mock = backend as? MockKartBackend,
               let today = StoreDay.day(iso: profile.today) {          // Act 1: "next Saturday is Leo's soccer team party"
                let weekday = ((today % 7) + 11) % 7                  // 0 = Sunday … 6 = Saturday
                let nextSaturday = today + ((6 - weekday + 7) % 7 == 0 ? 7 : (6 - weekday + 7) % 7)
                try? await mock.remember(kind: "event", text: "Leo's soccer team party, pasta for 12",
                                         eventDate: StoreDay.iso(nextSaturday), items: [])
                listFor = mock.memberProfile?.memories.first { $0.title == "Leo's soccer team party" }?.id
                return "Got it, I'll remember Leo's party on Saturday. Want me to save a list for it?"
            }
            if !words.isDisjoint(with: Self.yesWords), let memoryId = listFor, let mock = backend as? MockKartBackend {
                listFor = nil                                          // "Yes": pasta for 12, the Parmesan left to its card
                try? await mock.saveForLater(memoryId: memoryId, items: [
                    PlanItem(productId: "barilla-spaghetti", reason: "Leo's party", qty: 3),
                    PlanItem(productId: "rao-marinara", reason: "Leo's party", qty: 2)])
                return "Saved: three boxes of spaghetti and two jars of marinara for Leo's soccer team party."
            }
        }

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
            if backend.cart.memberId != nil, let profile = backend.memberProfile, let event = savedEvent(profile) {
                let listed = Set(backend.cart.plan.map(\.productId))     // "Want me to put up the list?" "Yes."
                try? await backend.setPlan(backend.cart.plan + (event.items ?? []).filter { !listed.contains($0.productId) }
                    .map { PlanItem(productId: $0.productId, reason: event.title, qty: $0.qty) })
                return backend.cart.nextStep.map { "Done, it's on your list. First stop: \($0)." } ?? "Done, it's on your list."
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
        case .tripContext, .cardResponse, .uiAction, .reconnected, .lull, .memberForgotten, .memberIdle:
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
