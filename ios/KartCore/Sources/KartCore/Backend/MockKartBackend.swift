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
    public private(set) var receipt: Receipt?
    public private(set) var memberProfile: MemberProfile?

    @ObservationIgnored private let clock: @MainActor () -> Date
    @ObservationIgnored private var nextEventId: Int64 = 1
    @ObservationIgnored private var nextTranscriptId: Int64 = 1
    @ObservationIgnored private var members: [String: MockMemberStore] = [:]
    @ObservationIgnored private var nextMemoryId = 100

    public init(catalog: Catalog, cartId: String = "7", clock: @escaping @MainActor () -> Date = { .now }) {
        self.catalog = catalog
        self.cart = .empty(cartId: cartId)
        self.clock = clock
    }

    private var now: Date { clock() }

    // MARK: KartBackend

    public func startTrip() async throws {
        cart = CartState(cartId: cart.cartId, tripId: UUID(), items: [], itemCount: 0, total: 0, savings: 0,
                         plan: [], suggestedDeals: [], status: .shopping, tripStartedAt: now, updatedAt: now,
                         features: cart.features,                 // feature switches belong to the cart, not the trip
                         memberRev: cart.memberRev, demoDate: cart.demoDate)   // so does the demo date; members don't
        memberProfile = nil
        events = []
        transcript = []
        receipt = nil
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
        // As the backend: a "Yes" puts the product on the plan, which consumes the suggestion, and the
        // next eligible pairing is offered right away.
        if let suggestion = cart.suggestion, plan.contains(where: { $0.productId == suggestion.productId }) {
            cart.suggestion = nil
        }
        offerNextPairing()
        recompute()
    }

    public func dismissSuggestion() async throws {
        cart.suggestion = nil
        refreshNudge()                                          // an over nudge waiting behind the deal card shows now
        cart.updatedAt = now
    }

    public func setStatus(_ status: TripStatus) async throws {
        guard status != .paid else { throw KartBackendError.invalidStatus }
        cart.status = status
        if status == .checkout { nudgeIfShort() }
        cart.updatedAt = now
    }

    public func dismissNudge(_ action: NudgeAction) async throws {
        guard let nudge = cart.nudge else { return }
        if action == .keep, nudge.kind == .over, let index = cart.plan.firstIndex(where: { $0.productId == nudge.productId }) {
            cart.plan[index].qty = nudge.have                    // keep: the list now wants what's in the cart
        }
        if !cart.nudged.contains(nudge.key) { cart.nudged.append(nudge.key) }
        cart.nudge = nil
        if action == .shop, cart.status == .checkout { cart.status = .shopping }   // "go get them"
        recompute()
    }

    public func setFeature(_ feature: String, on: Bool) async throws {
        cart.features[feature] = on
        if !cart.quantityNudgesOn { cart.nudge = nil }
        if !cart.memberMemoryOn { cart.memberId = nil; memberProfile = nil }
        cart.updatedAt = now
    }

    public func checkout(provider: String) async throws -> Receipt {
        let unresolved = events.filter(\.needsConfirmation).count
        guard unresolved == 0 else { throw KartBackendError.unresolvedItems(count: unresolved) }
        if let receipt, receipt.tripId == cart.tripId { return receipt }
        let duration = cart.tripStartedAt.map { Int(now.timeIntervalSince($0)) } ?? 0
        let receipt = Receipt(id: 1, cartId: cart.cartId, tripId: cart.tripId, total: cart.total, savings: cart.savings ?? 0,
                              itemCount: cart.itemCount, durationS: duration, provider: provider, status: "paid",
                              items: cart.items, createdAt: now)
        self.receipt = receipt
        if let member = cart.memberId {                       // a member's bill becomes their history
            let day = memberToday
            members[member]?.purchases += cart.items
                .filter { !MockMemberStore.sensitive.contains(catalog.product($0.productId)?.category ?? "") }
                .map { MockMemberStore.Purchase(productId: $0.productId, day: day, qty: $0.qty, price: $0.price) }
        }
        cart.status = .paid
        cart.updatedAt = now
        return receipt
    }

    public func endTrip() async throws {
        try await setStatus(.idle)
    }

    public func appendTranscript(_ role: TranscriptLine.Role, _ text: String) async throws {
        transcript.append(TranscriptLine(id: nextTranscriptId, role: role, text: text, createdAt: now))
        nextTranscriptId += 1
    }

    // MARK: Member memory (v0.14 beta)

    /// The cart's "today": the demo date when set, else the store's real day.
    private var memberToday: Int { cart.demoDate.flatMap(StoreDay.day(iso:)) ?? StoreDay.day(now) }

    private var liveDealProducts: Set<String> {
        Set(catalog.deals.filter { $0.endsAt.map { $0 > now } ?? true }.map(\.productId))
    }

    public func signIn(memberId: String) async throws {
        guard cart.memberMemoryOn else { throw KartBackendError.featureOff }
        if members[memberId] == nil {
            members[memberId] = memberId == "1029" ? .dylan(today: memberToday, catalog: catalog) : .empty(today: memberToday)
        }
        cart.memberId = memberId
        cart.updatedAt = now
        await refreshMemberProfile()
    }

    public func signOut() async throws {
        cart.memberId = nil
        memberProfile = nil
        cart.updatedAt = now
    }

    public func refreshMemberProfile() async {
        guard let id = cart.memberId, let store = members[id] else { memberProfile = nil; return }
        let taken = Set(cart.plan.map(\.productId) + cart.items.map(\.productId))
        memberProfile = store.profile(memberId: id, today: memberToday, taken: taken, catalog: catalog,
                                      liveDeals: liveDealProducts)
    }

    public func forgetMemory(id: Int) async throws {
        guard let member = cart.memberId else { return }
        members[member]?.memories.removeAll { $0.id == id }
        cart.memberRev += 1
        await refreshMemberProfile()
    }

    public func forgetMember() async throws {
        guard let member = cart.memberId else { return }
        members[member] = .empty(today: memberToday)          // like a deleted member signing up again
        try await signOut()
    }

    public func setDemoDate(_ date: String?) async throws {
        guard cart.memberMemoryOn else { throw KartBackendError.featureOff }
        cart.demoDate = date
        cart.updatedAt = now
        await refreshMemberProfile()
    }

    /// What the agent's `remember` + `save_for_later` do (the scripted mock voice uses it).
    public func remember(kind: String, text: String, eventDate: String?, items: [PlanItem]) async throws {
        guard let member = cart.memberId else { throw KartBackendError.noActiveTrip }
        let saved = items.compactMap { item in
            catalog.product(item.productId).map { SavedItem(productId: item.productId, shortName: $0.shortName, qty: item.qty) }
        }
        members[member]?.memories.append(.init(id: nextMemoryId, kind: kind, text: text,
                                              eventDay: eventDate.flatMap(StoreDay.day(iso:)),
                                              items: saved.isEmpty ? nil : saved, createdDay: memberToday))
        nextMemoryId += 1
        cart.memberRev += 1
        await refreshMemberProfile()
    }

    // MARK: Mock-only controls (debug panel, tests, scenarios)

    /// What the Pi's `apply_cart_event` call does.
    public func simulateVision(_ type: CartEventType, productId: String?, confidence: Double, label: String) async {
        record(type, productId: productId, confidence: confidence, source: .vision, label: label)
    }

    public func setConnection(_ state: ConnectionState) {
        connection = state
    }

    /// The merchant agent creating or changing a deal (P10). A newly created eligible deal replaces
    /// the open suggestion (contract v0.9).
    public func pushDeal(_ deal: Deal) async {
        let isNew = !catalog.deals.contains { $0.id == deal.id }
        if let index = catalog.deals.firstIndex(where: { $0.id == deal.id }) {
            catalog.deals[index] = deal
        } else {
            catalog.deals.append(deal)
        }
        repriceForDrops()
        let inCart = Set(cart.items.map(\.productId))
        if isNew, isEligible(deal), !inCart.isDisjoint(with: deal.pairsWith) {
            offer(deal)
        }
        recompute()
    }

    public func removeDeal(id: String) async {
        catalog.deals.removeAll { $0.id == id }
        recompute()
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
        case .added:
            add(product)
            offerNextPairing()
        case .removed:
            remove(product)
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
        if cart.suggestion?.productId == product.id { cart.suggestion = nil }
    }

    private func remove(_ product: Product) {
        guard let index = cart.items.firstIndex(where: { $0.productId == product.id }) else { return }
        cart.items[index].qty -= 1
        if cart.items[index].qty <= 0 { cart.items.remove(at: index) }
    }

    // MARK: Quantity nudges (v0.12 beta), as the backend: plan items only, once per product per direction per
    // trip, a pending deal suggestion first, and a nudge clears itself when the counts match.

    private func inCart(_ productId: String) -> Int {
        cart.items.filter { $0.productId == productId }.reduce(0) { $0 + $1.qty }
    }

    private func mayNudge(_ key: String) -> Bool {
        cart.quantityNudgesOn && cart.suggestion == nil && !cart.nudged.contains(key)
    }

    /// Clears a nudge whose counts now match, else raises the first "over" one (plan items only: impulse buys are
    /// never nudged). Runs after every change, so one that waited behind a deal card shows once the card is answered.
    private func refreshNudge() {
        clearMatchedNudge()
        guard cart.nudge == nil else { return }
        for line in cart.plan {
            guard let product = catalog.product(line.productId) else { continue }
            nudgeIfOver(product, line: line)
            if cart.nudge != nil { return }
        }
    }

    private func nudgeIfOver(_ product: Product, line: PlanItem) {
        let have = inCart(product.id)
        guard have > line.qty, mayNudge("over:\(product.id)") else { return }
        cart.nudged.append("over:\(product.id)")                 // raised once per trip, answered or not
        cart.nudge = Nudge(productId: product.id, name: product.shortName, kind: .over, have: have, need: line.qty,
                           basis: line.basis, text: "That's your \(Self.ordinal(have)) \(product.shortName). Your list says \(line.qty). Keep it?",
                           savings: effectivePrice(of: product).price * Decimal(have - line.qty),
                           aisle: catalog.section(product.section)?.aisleLabel, at: now)
    }

    /// At checkout, as the backend: one combined nudge with every short in-stock plan item, in walking order.
    private func nudgeIfShort() {
        var items: [NudgeItem] = []
        for line in cart.plan {
            guard let product = catalog.product(line.productId), product.stock > 0 else { continue }
            let have = inCart(line.productId)
            guard have < line.qty, mayNudge("under:\(line.productId)") else { continue }
            items.append(NudgeItem(productId: line.productId, name: product.shortName, have: have, need: line.qty,
                                   aisle: catalog.section(product.section)?.aisleLabel ?? product.section))
        }
        guard let first = items.first else { return }
        let names = items.compactMap(\.name)
        let list = names.count == 1 ? names[0] : names.dropLast().joined(separator: ", ") + " and " + names.last!
        cart.nudged.append(contentsOf: items.map { "under:\($0.productId)" })
        cart.nudge = Nudge(productId: first.productId, name: first.name, kind: .under, have: first.have, need: first.need,
                           text: "Before you go: you still need \(list).", aisle: first.aisle, at: now, items: items)
    }

    private func clearMatchedNudge() {
        guard let nudge = cart.nudge, let line = cart.plan.first(where: { $0.productId == nudge.productId }) else { return }
        if inCart(nudge.productId) == line.qty { cart.nudge = nil }
    }

    private static func ordinal(_ n: Int) -> String {
        let suffix = (11...13).contains(n % 100) ? "th" : [1: "st", 2: "nd", 3: "rd"][n % 10] ?? "th"
        return "\(n)\(suffix)"
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

    /// As the backend: a deal paired with something in the cart, the most recently added pairing first.
    private func offerNextPairing() {
        guard cart.suggestion == nil else { return }
        let recentFirst = cart.items.sorted { ($0.lastAddedAt ?? $0.addedAt) > ($1.lastAddedAt ?? $1.addedAt) }
        for item in recentFirst {
            if let deal = catalog.deals.first(where: { $0.pairsWith.contains(item.productId) && isEligible($0) }) {
                offer(deal)
                return
            }
        }
    }

    private func isEligible(_ deal: Deal) -> Bool {
        let active = deal.endsAt.map { $0 > now } ?? true
        // As the backend (§3a): not in the cart, not on the plan, and not offered yet this trip.
        return active
            && !cart.items.contains { $0.productId == deal.productId }
            && !cart.plan.contains { $0.productId == deal.productId }
            && !cart.suggestedDeals.contains(deal.id)
    }

    private func offer(_ deal: Deal) {
        guard let product = catalog.product(deal.productId) else { return }
        let aisle = catalog.section(product.section)?.aisleLabel ?? product.section
        cart.suggestion = Suggestion(productId: product.id, dealId: deal.id,
                                     text: "\(product.shortName) is \(deal.label) in \(aisle). Want it?",
                                     name: product.shortName, dealLabel: deal.label, aisle: aisle,
                                     section: product.section, price: product.price,
                                     salePrice: effectivePrice(of: product).price, offeredAt: now)
        cart.suggestedDeals.append(deal.id)
    }

    /// P10: drops reach items already in the cart; increases never do.
    private func repriceForDrops() {
        for index in cart.items.indices {
            guard let product = catalog.product(cart.items[index].productId) else { continue }
            let (price, deal) = effectivePrice(of: product)
            if price < cart.items[index].price {
                cart.items[index].price = price
                cart.items[index].dealLabel = deal?.label
                cart.items[index].dealId = deal?.id
            }
        }
    }

    private func recompute() {
        cart.total = cart.items.reduce(0) { $0 + $1.price * Decimal($1.qty) }
        cart.savings = cart.items.reduce(0) { $0 + (($1.listPrice ?? $1.price) - $1.price) * Decimal($1.qty) }
        cart.itemCount = cart.items.reduce(0) { $0 + $1.qty }
        refreshPlan()
        refreshNudge()
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
