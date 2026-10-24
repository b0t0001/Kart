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
    @ObservationIgnored private var seenEvents: Set<UUID> = []
    @ObservationIgnored private var seenNewDealCards: Set<String> = []
    @ObservationIgnored private var announcedDeals: Set<String> = []
    @ObservationIgnored private var pendingDeals: [(deal: Deal, due: Date)] = []
    @ObservationIgnored private var lastActivity: Date
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
                    baselineDeals: baselineDeals, acknowledgedNewDeals: acknowledgedNewDeals)
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
        defer { lastCart = cart }
        guard let previous = lastCart else { return }
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
        guard !announcedDeals.contains(suggestion.dealId) else { return }
        announcedDeals.insert(suggestion.dealId)
        sounds.play(.card)
        voice.send(.suggestion(suggestion))
        react(.happyBounce)
    }

    // MARK: Intents

    public func startTrip() async {
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
        do { try await backend.startTrip() } catch { return }
        lastCart = backend.cart
        baselineDeals = Dictionary(backend.catalog.deals.map { ($0.id, $0.label) }, uniquingKeysWith: { first, _ in first })
        lastActivity = clock()
        react(.wave)
        guard let tripId = backend.cart.tripId else { return }
        await voice.start(cartId: backend.cart.cartId, tripId: tripId)
        voice.send(.tripContext(cartId: backend.cart.cartId, tripId: tripId))
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
                try? await backend.resolveUnknown(eventId: eventId)
            default:
                break
            }
        case .deal(let suggestion):
            if action == .yes { await addToPlan(suggestion.productId) }
            if action == .no { try? await backend.dismissSuggestion() }
        case .newDeal(let deal):
            if action == .addIt { await addToPlan(deal.productId) }
            acknowledgedNewDeals.insert("\(deal.id)|\(deal.label)")
        case .offline:
            if action == .retry { await retryVoice() }
        }
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
            guard result.approved else { paymentState = .failed(Self.paymentFailedMessage); return }
            let receipt = try await backend.checkout(provider: payment.name)
            paymentState = .done(receipt)
            sounds.play(.success)
            react(.celebrate)
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
        voice.send(.tripContext(cartId: backend.cart.cartId, tripId: tripId))
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

    // MARK: Helpers

    private func confirm(eventId: UUID, as productId: String) async {
        locallyResolved.insert(eventId)
        try? await backend.applyManualEvent(.added, productId: productId, resolving: eventId)
    }

    private func addToPlan(_ productId: String) async {
        guard !backend.cart.plan.contains(where: { $0.productId == productId }) else { return }
        try? await backend.setPlan(backend.cart.plan + [PlanItem(productId: productId, reason: "deal")])
    }

    private func react(_ reaction: AvatarReaction) {
        self.reaction = ReactionEvent(reaction: reaction)
    }
}
