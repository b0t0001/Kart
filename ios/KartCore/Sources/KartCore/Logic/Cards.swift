import Foundation

public enum CardAction: Sendable, Equatable, Hashable {
    case yes, no, somethingElse, remove, addIt, gotIt, retry
    case choose(productId: String)

    public var title: String {
        switch self {
        case .yes: "Yes"
        case .no: "No thanks"
        case .somethingElse: "Not this"
        case .remove: "Remove"
        case .addIt: "Add it"
        case .gotIt: "Got it"
        case .retry: "Retry"
        case .choose: ""
        }
    }
}

/// Something that needs the shopper's attention or a decision. One is visible at a time.
public struct Card: Identifiable, Sendable, Equatable {
    public enum Kind: Sendable, Equatable {
        case confirmItem(eventId: UUID, candidates: [Product])
        case offline
        case deal(Suggestion)
        case newDeal(Deal)
    }

    public let id: String
    public let kind: Kind
    public let title: String
    public let actions: [CardAction]

    public init(id: String, kind: Kind, title: String, actions: [CardAction]) {
        self.id = id
        self.kind = kind
        self.title = title
        self.actions = actions
    }
}

public struct CardContext: Sendable {
    public var cart: CartState
    public var events: [CartEvent]
    public var catalog: Catalog
    public var now: Date
    public var voiceOnline: Bool
    /// event_id UUIDs the shopper answered before the backend caught up.
    public var locallyResolved: Set<UUID>
    /// Deal id → label when the trip started.
    public var baselineDeals: [String: String]
    /// "\(deal.id)|\(deal.label)"
    public var acknowledgedNewDeals: Set<String>

    public init(cart: CartState, events: [CartEvent], catalog: Catalog, now: Date, voiceOnline: Bool,
                locallyResolved: Set<UUID>, baselineDeals: [String: String], acknowledgedNewDeals: Set<String>) {
        self.cart = cart
        self.events = events
        self.catalog = catalog
        self.now = now
        self.voiceOnline = voiceOnline
        self.locallyResolved = locallyResolved
        self.baselineDeals = baselineDeals
        self.acknowledgedNewDeals = acknowledgedNewDeals
    }
}

public enum CardDeriver {
    static let confidentMatch = 0.5

    /// Cards in priority order: confirm items, offline, the deal suggestion, then new store deals.
    public static func cards(_ ctx: CardContext) -> [Card] {
        confirmCards(ctx) + offlineCards(ctx) + dealCards(ctx) + newDealCards(ctx)
    }

    private static func confirmCards(_ ctx: CardContext) -> [Card] {
        ctx.events
            .filter { $0.needsConfirmation && !ctx.locallyResolved.contains($0.eventId) }
            .sorted { $0.id < $1.id }
            .map { event in
                let matches = LabelMatcher.matches(for: event.label ?? "", in: ctx.catalog.products)
                let candidates = matches.map(\.product)
                if let best = matches.first, best.score >= confidentMatch {
                    return Card(id: "confirm-\(event.id)", kind: .confirmItem(eventId: event.eventId, candidates: candidates),
                                title: "Is this the \(best.product.shortName)?", actions: [.yes, .somethingElse, .remove])
                }
                return Card(id: "confirm-\(event.id)", kind: .confirmItem(eventId: event.eventId, candidates: candidates),
                            title: "What did you just add?", actions: [.somethingElse, .remove])
            }
    }

    private static func offlineCards(_ ctx: CardContext) -> [Card] {
        ctx.voiceOnline ? [] : [Card(id: "offline", kind: .offline, title: "Voice is offline. Tap to retry.", actions: [.retry])]
    }

    private static func dealCards(_ ctx: CardContext) -> [Card] {
        guard let suggestion = ctx.cart.suggestion else { return [] }
        return [Card(id: "deal-\(suggestion.dealId)", kind: .deal(suggestion), title: suggestion.text, actions: [.yes, .no])]
    }

    private static func newDealCards(_ ctx: CardContext) -> [Card] {
        let planned = Set(ctx.cart.plan.map(\.productId))
        let inCart = Set(ctx.cart.items.map(\.productId))
        let relevantProducts = planned.union(inCart)
        return ctx.catalog.deals.compactMap { deal in
            let key = "\(deal.id)|\(deal.label)"
            let active = deal.endsAt.map { $0 > ctx.now } ?? true
            let relevant = relevantProducts.contains(deal.productId) || !relevantProducts.isDisjoint(with: deal.pairsWith)
            guard ctx.baselineDeals[deal.id] != deal.label, !ctx.acknowledgedNewDeals.contains(key), active,
                  deal.id != ctx.cart.suggestion?.dealId, relevant,
                  let product = ctx.catalog.product(deal.productId) else { return nil }
            let owned = planned.contains(deal.productId) || inCart.contains(deal.productId)
            return Card(id: "newdeal-\(key)", kind: .newDeal(deal), title: "New deal: \(product.shortName) \(deal.label)",
                        actions: owned ? [.gotIt] : [.addIt, .gotIt])
        }
    }
}
