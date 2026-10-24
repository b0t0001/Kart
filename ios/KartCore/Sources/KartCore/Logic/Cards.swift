import Foundation

public enum CardAction: Sendable, Equatable, Hashable {
    case yes, no, somethingElse, remove, addIt, gotIt, keepIt, goGetIt, skipIt, goGetThem, skip, retry
    case choose(productId: String)

    public var title: String {
        switch self {
        case .yes: "Yes"
        case .no: "No thanks"
        case .somethingElse: "Not this"
        case .remove: "Remove"
        case .addIt: "Add it"
        case .gotIt: "Got it"
        case .keepIt: "Keep it"
        case .goGetIt: "Go get it"
        case .skipIt: "Skip it"
        case .goGetThem: "Go get them"
        case .skip: "Skip"
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
        case nudge(Nudge)
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

    /// Cards in priority order: confirm items, offline, the deal suggestion, a quantity nudge (beta), then new store
    /// deals.
    public static func cards(_ ctx: CardContext) -> [Card] {
        confirmCards(ctx) + offlineCards(ctx) + dealCards(ctx) + nudgeCards(ctx) + newDealCards(ctx)
    }

    /// Only with the cart's `quantity_nudges` flag on; with it off nothing changes.
    private static func nudgeCards(_ ctx: CardContext) -> [Card] {
        guard ctx.cart.quantityNudgesOn, let nudge = ctx.cart.nudge else { return [] }
        // Short at checkout: the bill is where the shopper is, so offer the way back before they pay.
        if nudge.kind == .under, let items = nudge.items, items.count > 1 {   // checkout: the whole list, with aisles
            let named = items.map { item in item.aisle.map { "\(item.name ?? item.productId) (\($0))" } ?? (item.name ?? item.productId) }
            let list = named.dropLast().joined(separator: ", ") + " and " + named.last!
            return [Card(id: "nudge-\(nudge.key)", kind: .nudge(nudge), title: "Before you go: you still need \(list).",
                         actions: [.goGetThem, .skip])]
        }
        let actions: [CardAction] = switch (nudge.kind, ctx.cart.status) {
        case (.over, _): [.keepIt, .gotIt]
        case (.under, .checkout): [.goGetIt, .skipIt]
        case (.under, _): [.gotIt]
        }
        return [Card(id: "nudge-\(nudge.key)", kind: .nudge(nudge), title: nudge.text, actions: actions)]
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
        guard let suggestion = ctx.cart.suggestion,
              !ctx.cart.plan.contains(where: { $0.productId == suggestion.productId }) else { return [] }
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
