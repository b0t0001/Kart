import Foundation
import Observation

public enum PaymentState: Sendable, Equatable {
    case idle, processing, failed(String), done(Receipt)
}

/// A one-shot avatar reaction; a new `id` plays it again.
public struct ReactionEvent: Sendable, Equatable, Identifiable {
    public let id: UUID
    public let reaction: AvatarReaction
    /// Lets a view that appears just after (Greeting after the wave) still play it.
    public let at: Date

    public init(id: UUID = UUID(), reaction: AvatarReaction, at: Date = .now) {
        self.id = id
        self.reaction = reaction
        self.at = at
    }
}

/// Ties the backend, the voice, payment and sounds together for the views.
@MainActor @Observable
public final class AppModel {
    public let backend: any KartBackend
    public let voice: any VoiceSession

    public private(set) var reaction: ReactionEvent?
    public private(set) var celebration: String?
    public private(set) var paymentState: PaymentState = .idle
    public private(set) var highlightUnresolved = false

    private var locallyResolved: Set<UUID> = []
    private var acknowledgedNewDeals: Set<String> = []
    private var baselineDeals: [String: String] = [:]

    @ObservationIgnored private let payment: any PaymentProvider
    @ObservationIgnored private let sounds: any SoundPlaying
    @ObservationIgnored private let clock: @MainActor () -> Date
    @ObservationIgnored private var lastCart: CartState?
    @ObservationIgnored private var lastSuggestionDealId: String?
    @ObservationIgnored private var lastNudgeKey: String?
    @ObservationIgnored private var seenEvents: Set<UUID> = []
    @ObservationIgnored private var seenNewDealCards: Set<String> = []
    @ObservationIgnored private var announcedDeals: Set<String> = []
    @ObservationIgnored private var pendingDeals: [(deal: Deal, due: Date)] = []
    @ObservationIgnored private var lastActivity: Date
    /// Member memory beta: the lull was sent this trip / the For you card was dismissed this trip.
    @ObservationIgnored private var lullSent = false
    private var forYouDismissed = false
    @ObservationIgnored private var bindings: [Task<Void, Never>] = []

    public static let dealAnnouncementGrace: TimeInterval = 1.5
    static let paymentFailedMessage = "Payment didn't go through. Try again."

    public init(backend: any KartBackend, voice: any VoiceSession, payment: any PaymentProvider,
                sounds: any SoundPlaying, clock: @escaping @MainActor () -> Date = { .now }) {
        self.backend = backend
        self.voice = voice
        self.payment = payment
        self.sounds = sounds
        self.clock = clock
        self.lastActivity = clock()
    }

    // MARK: Derived state

    public var screen: Screen { TripRouter.screen(cart: backend.cart, transcript: backend.transcript) }

    public var cards: [Card] { CardDeriver.cards(context(catalog: backend.catalog)) }

    public var visibleCard: Card? { cards.first }

    public var unresolvedCount: Int {
        cards.filter { if case .confirmItem = $0.kind { true } else { false } }.count
    }

    public var nextStop: NextStop? { NextStop.from(cart: backend.cart, catalog: backend.catalog) }

    public var avatarMood: AvatarMood { AvatarMood(voice.state) }

    private func context(catalog: Catalog) -> CardContext {
        CardContext(cart: backend.cart, events: backend.events, catalog: catalog, now: clock(),
                    voiceOnline: voice.state != .offline, locallyResolved: locallyResolved,
                    baselineDeals: baselineDeals, acknowledgedNewDeals: acknowledgedNewDeals,
                    agentPrompt: voice.agentPrompt)
    }

    // MARK: Live updates

    /// App only: follows the backend and feeds `ingest`. Tests call `ingest` directly.
    public func bind() {
        bindings.forEach { $0.cancel() }
        bindings = [
            Task { [weak self] in
                guard let self else { return }
                for await cart in Observations({ self.backend.cart }) { self.ingest(cart: cart) }
            },
            Task { [weak self] in
                guard let self else { return }
                for await events in Observations({ self.backend.events }) { self.ingest(events: events) }
            },
            Task { [weak self] in
                guard let self else { return }
                for await catalog in Observations({ self.backend.catalog }) {
                    self.ingest(catalog: catalog)
                    Task { [weak self] in
                        try? await Task.sleep(for: .seconds(Self.dealAnnouncementGrace))
                        guard let self else { return }
                        self.flushDealAnnouncements(now: self.clock())
                    }
                }
            },
        ]
    }

    public func ingest(cart: CartState) {
        if let previous = lastCart, previous.tripId == cart.tripId, let seen = previous.updatedAt,
           let updated = cart.updatedAt, updated < seen {
            return              // an older refetch that landed late: replaying it would announce a phantom remove and re-add
        }
        defer { lastCart = cart }
        guard let previous = lastCart else { return }
        if previous.tripId != cart.tripId {               // a reset from outside the app (laptop, another iPad)
            resetLocalTripState()
            baselineDeals = Dictionary(backend.catalog.deals.map { ($0.id, $0.label) }, uniquingKeysWith: { first, _ in first })
            lastActivity = clock()
            return
        }
        let changes = CartDiff.changes(from: previous, to: cart)
        for change in changes {
            switch change {
            case .added(let productId):
                sounds.play(.added)
                voice.send(.cartChanged(change))
                if cart.plan.contains(where: { $0.productId == productId }) { react(.happyBounce) }
            case .removed:
                sounds.play(.removed)
                voice.send(.cartChanged(change))
            case .priceDropped(let productId, let from, let to):
                let name = backend.catalog.product(productId)?.shortName ?? "An item"
                celebration = "\(name) just dropped \(Money.compact(from - to)). You saved."
                voice.send(.cartChanged(change))
            }
        }
        if cart.quantityNudgesOn, let nudge = cart.nudge {      // beta: Kart says each nudge once
            let key = "\(nudge.key)|\(nudge.at.map { "\($0.timeIntervalSince1970)" } ?? "")"
            if key != lastNudgeKey {
                lastNudgeKey = key
                voice.send(.nudge(nudge))
                sounds.play(.card)
            }
        }
        if let suggestion = cart.suggestion {
            if suggestion.dealId != lastSuggestionDealId {
                lastSuggestionDealId = suggestion.dealId
                announceSuggestion(suggestion)
            }
        } else {
            lastSuggestionDealId = nil
        }
        if previous != cart { lastActivity = clock() }
    }

    public func ingest(events: [CartEvent]) {
        for event in events where event.needsConfirmation && !seenEvents.contains(event.eventId) {
            seenEvents.insert(event.eventId)
            sounds.play(.card)
            react(.curiousTilt)
            voice.send(.uiAction("unknown_item"))   // Kart asks the shopper to look at the card
        }
    }

    /// New store deals wait out a short grace: the same deal may arrive as the cart's suggestion,
    /// which is the better line.
    public func ingest(catalog: Catalog) {
        for card in CardDeriver.cards(context(catalog: catalog)) {
            guard case .newDeal(let deal) = card.kind, !seenNewDealCards.contains(card.id) else { continue }
            seenNewDealCards.insert(card.id)
            pendingDeals.append((deal, clock().addingTimeInterval(Self.dealAnnouncementGrace)))
        }
    }

    public func flushDealAnnouncements(now: Date) {
        let due = pendingDeals.filter { $0.due <= now }
        pendingDeals.removeAll { $0.due <= now }
        for (deal, _) in due where !announcedDeals.contains(deal.id) && backend.cart.suggestion?.dealId != deal.id {
            announcedDeals.insert(deal.id)
            sounds.play(.card)
            voice.send(.dealChanged(deal))
        }
    }

    private func announceSuggestion(_ suggestion: Suggestion) {
        pendingDeals.removeAll { $0.deal.id == suggestion.dealId }
        guard !announcedDeals.contains(suggestion.dealId),
              !backend.cart.plan.contains(where: { $0.productId == suggestion.productId }) else { return }
        announcedDeals.insert(suggestion.dealId)
        sounds.play(.card)
        voice.send(.suggestion(suggestion))
        react(.happyBounce)
    }

    // MARK: Intents

    public func startTrip(memberId: String? = nil) async {
        resetLocalTripState()
        do { try await backend.startTrip() } catch { return }
        if let memberId, backend.cart.memberMemoryOn {
            try? await backend.signIn(memberId: memberId)      // the beta switched off mid-session: shop as a guest
        }
        lastCart = backend.cart
        baselineDeals = Dictionary(backend.catalog.deals.map { ($0.id, $0.label) }, uniquingKeysWith: { first, _ in first })
        lastActivity = clock()
        react(.wave)
        guard let tripId = backend.cart.tripId else { return }
        await voice.start(cartId: backend.cart.cartId, tripId: tripId)
        voice.send(.tripContext(cartId: backend.cart.cartId, tripId: tripId, memberId: backend.cart.memberId))
    }

    private func resetLocalTripState() {
        lullSent = false
        forYouDismissed = false
        locallyResolved = []
        acknowledgedNewDeals = []
        paymentState = .idle
        highlightUnresolved = false
        celebration = nil
        announcedDeals = []
        pendingDeals = []
        seenEvents = []
        seenNewDealCards = []
        lastSuggestionDealId = nil
        lastNudgeKey = nil
    }

    /// Adopts a trip that started outside this model (a demo scenario, or an app relaunch mid-trip)
    /// without replaying it as new events: no chimes, no spoken lines, no "new deal" cards.
    public func resumeTrip() {
        lastCart = backend.cart
        lastSuggestionDealId = backend.cart.suggestion?.dealId
        announcedDeals = Set(backend.cart.suggestion.map { [$0.dealId] } ?? [])
        seenEvents = Set(backend.events.map(\.eventId))
        baselineDeals = Dictionary(backend.catalog.deals.map { ($0.id, $0.label) }, uniquingKeysWith: { first, _ in first })
        seenNewDealCards = []
        pendingDeals = []
        lastActivity = clock()
    }

    public func respond(to card: Card, with action: CardAction) async {
        voice.send(.cardResponse(cardId: card.id, action: action))
        noteActivity()
        switch card.kind {
        case .confirmItem(let eventId, let candidates):
            switch action {
            case .yes:
                guard let best = candidates.first else { return }
                await confirm(eventId: eventId, as: best.id)
            case .choose(let productId):
                await confirm(eventId: eventId, as: productId)
            case .remove:
                locallyResolved.insert(eventId)
                do { try await backend.resolveUnknown(eventId: eventId) } catch { locallyResolved.remove(eventId) }
            default:
                break
            }
        case .deal(let suggestion):
            if action == .yes { await addToPlan(suggestion.productId) }
            if action == .no { try? await backend.dismissSuggestion() }
        case .nudge:
            let answer: NudgeAction = switch action {
            case .keepIt: .keep
            case .goGetIt, .goGetThem: .shop                    // short at checkout: back to the aisles
            case .skipIt, .skip: .skip
            default: .ok
            }
            try? await backend.dismissNudge(answer)
        case .newDeal(let deal):
            if action == .addIt { await addToPlan(deal.productId) }
            acknowledgedNewDeals.insert("\(deal.id)|\(deal.label)")
        case .dealDigest, .digestDeal:                          // Kart hears the tap (above) and sends the next card
            voice.clearAgentPrompt()
        case .offline:
            if action == .retry { await retryVoice() }
        }
    }

    /// The list's + / − (quantity-nudge beta): a one-tap fix for a camera miscount, as a manual cart event.
    public func adjust(_ productId: String, by delta: Int) async {
        noteActivity()
        try? await backend.applyManualEvent(delta > 0 ? .added : .removed, productId: productId, resolving: nil)
    }

    public func beginCheckout() async {
        try? await backend.setStatus(.checkout)
        voice.send(.uiAction("checkout_tapped"))
    }

    public func resumeShopping() async {
        try? await backend.setStatus(.shopping)
    }

    public func pay() async {
        switch paymentState {
        case .processing, .done: return
        case .idle, .failed: break
        }
        guard unresolvedCount == 0 else { highlightUnresolved = true; return }
        highlightUnresolved = false
        guard let tripId = backend.cart.tripId else { return }
        paymentState = .processing
        do {
            let result = try await payment.pay(amount: backend.cart.total, tripId: tripId)
            guard backend.cart.tripId == tripId else { paymentState = .idle; return }   // reset while the card was tapped
            guard result.approved else { paymentState = .failed(Self.paymentFailedMessage); return }
            let receipt = try await backend.checkout(provider: payment.name)
            paymentState = .done(receipt)
            sounds.play(.success)
            react(.celebrate)
            voice.send(.uiAction("paid"))   // Kart says goodbye
        } catch {
            paymentState = .failed(Self.paymentFailedMessage)
        }
    }

    public func finishTrip() async {
        try? await backend.endTrip()
        voice.stop()
    }

    public func retryVoice() async {
        guard let tripId = backend.cart.tripId else { return }
        await voice.start(cartId: backend.cart.cartId, tripId: tripId)
        voice.send(.tripContext(cartId: backend.cart.cartId, tripId: tripId, memberId: backend.cart.memberId))
    }

    public func clearCelebration() {
        celebration = nil
    }

    public func stillShoppingPromptDue(now: Date) -> Bool {
        backend.cart.status == .shopping && now.timeIntervalSince(lastActivity) >= 600
    }

    public func noteActivity() {
        lastActivity = clock()
    }

    // MARK: Member memory (v0.14 beta)

    /// The signed-in member's profile, only while the cart's beta is on.
    public var member: MemberProfile? {
        backend.cart.memberMemoryOn && backend.cart.memberId != nil ? backend.memberProfile : nil
    }

    private var onListOrInCart: Set<String> {
        Set(backend.cart.plan.map(\.productId) + backend.cart.items.map(\.productId))
    }

    /// This week's picks not yet on the list or in the cart; empty once dismissed this trip.
    public var forYouPicks: [MemberPick] {
        guard !forYouDismissed, let member else { return [] }
        return member.picks.filter { !onListOrInCart.contains($0.productId) }
    }

    /// The nearest coming event with a saved list that isn't all on today's list yet.
    public var savedEvent: MemberMemory? {
        guard !forYouDismissed, let member else { return nil }
        let listed = Set(backend.cart.plan.map(\.productId))
        return member.memories.first { memory in
            memory.kind == "event" && memory.isUpcoming
                && (memory.items ?? []).contains { !listed.contains($0.productId) }
        }
    }

    public func addPick(_ pick: MemberPick) async {
        noteActivity()
        await addToPlan(pick.productId, reason: "for you")
    }

    /// "Shop it": the saved list joins today's, keeping what's already there.
    public func shopSavedList(_ memory: MemberMemory) async {
        noteActivity()
        let listed = Set(backend.cart.plan.map(\.productId))
        let added = (memory.items ?? []).filter { !listed.contains($0.productId) }
            .map { PlanItem(productId: $0.productId, reason: memory.title, qty: $0.qty) }
        guard !added.isEmpty else { return }
        try? await backend.setPlan(backend.cart.plan + added)
    }

    public func dismissForYou() {
        forYouDismissed = true
    }

    /// 40 quiet seconds while a member shops, with nothing on screen: Kart may ask its one question (once per trip).
    public func lullDue(now: Date) -> Bool {
        member != nil && !lullSent && backend.cart.status == .shopping && visibleCard == nil
            && now.timeIntervalSince(lastActivity) >= 40
    }

    public func sendLullIfDue(now: Date) {
        guard lullDue(now: now) else { return }
        lullSent = true
        voice.send(.lull)
    }

    /// "Fri, Oct 30 · demo date" while the demo fast-forward is set.
    public var demoDateLabel: String? {
        guard let day = backend.cart.demoDate.flatMap(StoreDay.day(iso:)) else { return nil }
        return "\(StoreDay.format(day, "EEE, MMM d")) · demo date"
    }

    public enum DemoJump: Sendable, Equatable {
        case today, plusDays(Int), dayBeforeNextEvent
    }

    /// The nearest event at least two days off (so "the day before" is still ahead).
    private var nextEvent: (title: String, day: Int)? {
        guard let member, let today = StoreDay.day(iso: member.today) else { return nil }
        return member.memories.compactMap { m -> (String, Int)? in
            guard m.kind == "event", let day = m.eventDate.flatMap(StoreDay.day(iso:)), day - today >= 2 else { return nil }
            return (m.title, day)
        }.min { $0.1 < $1.1 }
    }

    public var dayBeforeNextEventAvailable: Bool { nextEvent != nil }
    public var nextEventTitle: String? { nextEvent?.title }

    public func jumpDemoDate(to jump: DemoJump) async {
        let base = backend.cart.demoDate.flatMap(StoreDay.day(iso:)) ?? StoreDay.day(clock())
        let target: Int?
        switch jump {
        case .today: target = nil
        case .plusDays(let n): target = base + n
        case .dayBeforeNextEvent:
            guard let event = nextEvent else { return }
            target = event.day - 1
        }
        try? await backend.setDemoDate(target.map(StoreDay.iso))
    }

    // MARK: Helpers

    /// Hides the card at once; if the backend refuses, the card comes back (it still blocks checkout there).
    private func confirm(eventId: UUID, as productId: String) async {
        locallyResolved.insert(eventId)
        do { try await backend.applyManualEvent(.added, productId: productId, resolving: eventId) } catch {
            locallyResolved.remove(eventId)
        }
    }

    private func addToPlan(_ productId: String, reason: String = "deal") async {
        guard !backend.cart.plan.contains(where: { $0.productId == productId }) else { return }
        try? await backend.setPlan(backend.cart.plan + [PlanItem(productId: productId, reason: reason)])
    }

    private func react(_ reaction: AvatarReaction) {
        self.reaction = ReactionEvent(reaction: reaction)
    }
}
