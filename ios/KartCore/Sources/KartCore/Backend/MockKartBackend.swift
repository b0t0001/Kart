import Foundation
import Observation

/// An in-memory backend that imitates the Supabase rules as built (contract v0.8 §3a), so the app
/// can be built and demoed with no network.
@MainActor @Observable
public final class MockKartBackend: KartBackend {
    public private(set) var cart: CartState
    public private(set) var events: [CartEvent] = []
    public private(set) var catalog: Catalog
    public private(set) var transcript: [TranscriptLine] = []
    public private(set) var connection: ConnectionState = .online

    @ObservationIgnored private let clock: @MainActor () -> Date
    @ObservationIgnored private var nextEventId: Int64 = 1
    @ObservationIgnored private var nextTranscriptId: Int64 = 1

    public init(catalog: Catalog, cartId: String = "7", clock: @escaping @MainActor () -> Date = { .now }) {
        self.catalog = catalog
        self.cart = .empty(cartId: cartId)
        self.clock = clock
    }

    private var now: Date { clock() }

    // MARK: KartBackend

    public func startTrip() async throws {
        cart = CartState(cartId: cart.cartId, tripId: UUID(), items: [], itemCount: 0, total: 0, savings: 0,
                         plan: [], suggestedDeals: [], status: .shopping, tripStartedAt: now, updatedAt: now)
        events = []
        transcript = []
        nextEventId = 1
        nextTranscriptId = 1
    }

    public func applyManualEvent(_ type: CartEventType, productId: String, resolving eventId: UUID?) async throws {
        guard catalog.product(productId) != nil else { throw KartBackendError.unknownProduct(productId) }
        if let eventId { markResolved(eventId) }
        record(type, productId: productId, confidence: 1, source: .manual, label: nil)
    }

    public func resolveUnknown(eventId: UUID) async throws {
        markResolved(eventId)
        record(.removed, productId: nil, confidence: 1, source: .manual, label: nil)
    }

    public func setPlan(_ plan: [PlanItem]) async throws {
        cart.plan = plan
        recompute()
    }

    public func dismissSuggestion() async throws {
        cart.suggestion = nil
        cart.updatedAt = now
    }

    public func setStatus(_ status: TripStatus) async throws {
        cart.status = status
        cart.updatedAt = now
    }

    public func checkout(provider: String) async throws -> Receipt {
        throw KartBackendError.noActiveTrip
    }

    public func endTrip() async throws {
        try await setStatus(.idle)
    }

    public func appendTranscript(_ role: TranscriptLine.Role, _ text: String) async throws {
        transcript.append(TranscriptLine(id: nextTranscriptId, role: role, text: text, createdAt: now))
        nextTranscriptId += 1
    }

    // MARK: Mock-only controls (debug panel, tests, scenarios)

    /// What the Pi's `apply_cart_event` call does.
    public func simulateVision(_ type: CartEventType, productId: String?, confidence: Double, label: String) async {
        record(type, productId: productId, confidence: confidence, source: .vision, label: label)
    }

    public func setConnection(_ state: ConnectionState) {
        connection = state
    }

    // MARK: Rules

    private func record(_ type: CartEventType, productId: String?, confidence: Double, source: CartEventSource,
                        label: String?) {
        let product = productId.flatMap(catalog.product)
        events.append(CartEvent(id: nextEventId, eventId: UUID(), cartId: cart.cartId, tripId: cart.tripId, type: type,
                                productId: productId, confidence: confidence, source: source, label: label,
                                applied: product != nil, createdAt: now))
        nextEventId += 1
        guard let product else { cart.updatedAt = now; return }
        switch type {
        case .added: add(product)
        case .removed: remove(product)
        }
        recompute()
    }

    private func markResolved(_ eventId: UUID) {
        guard let index = events.firstIndex(where: { $0.eventId == eventId }) else { return }
        events[index].resolvedAt = now
    }

    private func add(_ product: Product) {
        let (price, deal) = effectivePrice(of: product)
        if let index = cart.items.firstIndex(where: { $0.productId == product.id }) {
            cart.items[index].qty += 1
            cart.items[index].lastAddedAt = now
            if price < cart.items[index].price {
                cart.items[index].price = price
                cart.items[index].dealLabel = deal?.label
                cart.items[index].dealId = deal?.id
            }
        } else {
            cart.items.append(CartItem(productId: product.id, name: product.name, shortName: product.shortName,
                                       price: price, listPrice: product.price, qty: 1, dealLabel: deal?.label,
                                       dealId: deal?.id, section: product.section, addedAt: now, lastAddedAt: now))
        }
        cart.location = CartLocation(section: product.section, source: "item", at: now)
    }

    private func remove(_ product: Product) {
        guard let index = cart.items.firstIndex(where: { $0.productId == product.id }) else { return }
        cart.items[index].qty -= 1
        if cart.items[index].qty <= 0 { cart.items.remove(at: index) }
    }

    /// Effective price after the product's active deal, rounded to cents.
    func effectivePrice(of product: Product) -> (price: Decimal, deal: Deal?) {
        guard let deal = catalog.activeDeal(for: product.id, at: now) else { return (product.price, nil) }
        let raw: Decimal = switch deal.type {
        case .amountOff: max(0, product.price - deal.value)
        case .percentOff: product.price * (100 - deal.value) / 100
        }
        var value = raw
        var rounded = Decimal()
        NSDecimalRound(&rounded, &value, 2, .plain)
        return (rounded, deal)
    }

    private func recompute() {
        cart.total = cart.items.reduce(0) { $0 + $1.price * Decimal($1.qty) }
        cart.savings = cart.items.reduce(0) { $0 + (($1.listPrice ?? $1.price) - $1.price) * Decimal($1.qty) }
        cart.itemCount = cart.items.reduce(0) { $0 + $1.qty }
        refreshPlan()
        cart.updatedAt = now
    }

    private func refreshPlan() {
        let inCart = Dictionary(cart.items.map { ($0.productId, $0.qty) }, uniquingKeysWith: +)
        let filled = cart.plan.map { line -> PlanItem in
            guard let product = catalog.product(line.productId) else { return line }
            var line = line
            line.name = product.shortName
            line.section = product.section
            line.aisle = catalog.section(product.section)?.aisleLabel
            line.inStock = product.stock > 0
            line.dealLabel = catalog.activeDeal(for: product.id, at: now)?.label
            line.done = (inCart[product.id] ?? 0) >= line.qty
            return line
        }
        let known = filled.filter { catalog.product($0.productId) != nil }
        let unknown = filled.filter { catalog.product($0.productId) == nil }
        let done = known.filter(\.done)
        var remaining = known.filter { !$0.done }
        var x = startX()
        var route: [PlanItem] = []
        while !remaining.isEmpty {
            var best = 0
            for i in remaining.indices where abs(centerX(remaining[i]) - x) < abs(centerX(remaining[best]) - x) {
                best = i
            }
            let next = remaining.remove(at: best)
            x = centerX(next)
            route.append(next)
        }
        cart.plan = done + route + unknown
        cart.nextStep = nextStep(route: route)
    }

    private func nextStep(route: [PlanItem]) -> String? {
        guard !cart.plan.isEmpty else { return nil }
        guard let line = route.first(where: { $0.inStock == true }), let product = catalog.product(line.productId) else {
            return "All done → Checkout"
        }
        let aisle = line.aisle ?? product.section
        return line.dealLabel.map { "\(aisle) → \(product.shortName), \($0)" } ?? "\(aisle) → \(product.shortName)"
    }

    private func startX() -> Double {
        if let section = cart.location.flatMap({ catalog.section($0.section) }) { return center(section) }
        return Double(catalog.layout.entrance.x)
    }

    private func centerX(_ line: PlanItem) -> Double {
        guard let section = catalog.product(line.productId).flatMap({ catalog.section($0.section) }) else { return .infinity }
        return center(section)
    }

    private func center(_ section: Section) -> Double { Double(section.x) + Double(section.w) / 2 }
}
