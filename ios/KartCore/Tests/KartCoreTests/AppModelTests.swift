import Foundation
import Observation
import Testing
@testable import KartCore

@MainActor @Observable final class RecordingVoice: VoiceSession {
    var state: VoiceState = .listening
    var outputLevel: Double = 0
    var isMuted = false
    var holdToTalk = false
    var isHeld = false
    var agentPrompt: AgentPrompt?
    var lastActiveAt: Date?
    var pauseCount = 0
    var resumeCount = 0
    var sent: [VoiceEvent] = []
    var startCount = 0
    var stopCount = 0

    func start(cartId: String, tripId: UUID) async { startCount += 1 }
    func stop() { stopCount += 1 }
    func setMuted(_ muted: Bool) { isMuted = muted }
    func setHeld(_ held: Bool) { isHeld = held }
    func clearAgentPrompt() { agentPrompt = nil }
    func send(_ event: VoiceEvent) { sent.append(event) }
    func pause() { pauseCount += 1; state = .paused }
    func resume() async { resumeCount += 1; state = .listening }
}

@MainActor final class RecordingSounds: SoundPlaying {
    var played: [SoundCue] = []
    func play(_ cue: SoundCue) { played.append(cue) }
}

@MainActor final class RecordingPayment: PaymentProvider {
    let name = "simulated"
    var calls = 0
    var result: Result<PaymentResult, any Error> = .success(PaymentResult(approved: true, reference: "SIM-1"))
    let delay: Duration

    init(delay: Duration) { self.delay = delay }

    func pay(amount: Decimal, tripId: UUID) async throws -> PaymentResult {
        calls += 1
        if delay > .zero { try? await Task.sleep(for: delay) }
        return try result.get()
    }
}

@MainActor struct TestRig {
    let model: AppModel
    let backend: MockKartBackend
    let voice: RecordingVoice
    let sounds: RecordingSounds
    let payment: RecordingPayment
    let clock: ManualClock
}

@MainActor func make(delay: Duration = .zero) throws -> TestRig {
    let clock = ManualClock()
    let backend = MockKartBackend(catalog: try Fixtures.catalog(), clock: { clock.now })
    let voice = RecordingVoice()
    let sounds = RecordingSounds()
    let payment = RecordingPayment(delay: delay)
    let model = AppModel(backend: backend, voice: voice, payment: payment, sounds: sounds, clock: { clock.now })
    return TestRig(model: model, backend: backend, voice: voice, sounds: sounds, payment: payment, clock: clock)
}

@MainActor @Test func startTripGreetsAndWaves() async throws {
    let t = try make(); await t.model.startTrip()
    #expect(t.backend.cart.status == .shopping && t.voice.startCount == 1)
    #expect(t.model.reaction?.reaction == .wave && t.model.screen == .greeting)
    #expect(t.voice.sent.first == .tripContext(cartId: "7", tripId: try #require(t.backend.cart.tripId)))
}
@MainActor @Test func addedPlanItemChimesBouncesAndTellsVoice() async throws {
    let t = try make(); await t.model.startTrip(); try await t.backend.setPlan(DemoScript.pastaPlan); t.model.ingest(cart: t.backend.cart)
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s"); t.model.ingest(cart: t.backend.cart)
    #expect(t.sounds.played.contains(.added) && t.model.reaction?.reaction == .happyBounce)
    #expect(t.voice.sent.contains(.cartChanged(.added(productId: "barilla-spaghetti"))))
    #expect(t.voice.sent.contains { if case .suggestion(let s) = $0 { s.dealId == "d-parm-3off" } else { false } })
    #expect(t.sounds.played.contains(.card))
}
@MainActor @Test func confirmCardYesAddsBestGuess() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.4, label: "jar of rao's marinara"); t.model.ingest(events: t.backend.events)
    #expect(t.model.reaction?.reaction == .curiousTilt)
    let card = try #require(t.model.visibleCard); await t.model.respond(to: card, with: .yes)
    #expect(t.backend.cart.items.map(\.productId) == ["rao-marinara"] && t.model.unresolvedCount == 0)
}
@MainActor @Test func dealCardYesAndNo() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
    await t.model.respond(to: try #require(t.model.visibleCard), with: .yes)
    #expect(t.backend.cart.plan.contains { $0.productId == "kirkland-parmesan" && $0.reason == "deal" })
    #expect(t.model.visibleCard?.title == "Garlic Bread is $1 off in Aisle 8. Want it?")   // the Yes consumed it; the next pairing pops

    await t.model.startTrip()                                // "No thanks" on a fresh trip
    await t.backend.simulateVision(.added, productId: "tostitos-salsa", confidence: 0.9, label: "salsa")   // suggests chips
    await t.model.respond(to: try #require(t.model.visibleCard), with: .no)
    #expect(t.backend.cart.suggestion == nil)
}
@MainActor @Test func pushedDealCelebratesDropAndAnnouncesNewDeal() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b"); t.model.ingest(cart: t.backend.cart)
    await t.backend.pushDeal(Deal(id: "d-bananas-50c", productId: "bananas", type: .amountOff, value: Decimal(string: "0.5")!, label: "50¢ off", pairsWith: [], endsAt: nil))
    t.model.ingest(cart: t.backend.cart); t.model.ingest(catalog: t.backend.catalog)
    #expect(!t.voice.sent.contains { if case .dealChanged = $0 { true } else { false } })   // waits out the grace period
    t.model.flushDealAnnouncements(now: t.clock.now + 2)
    #expect(t.model.celebration == "Bananas just dropped $0.50. You saved.")
    #expect(t.voice.sent.contains { if case .dealChanged(let d) = $0 { d.id == "d-bananas-50c" } else { false } })
    let card = try #require(t.model.cards.first { $0.id.hasPrefix("newdeal-") })
    await t.model.respond(to: card, with: .gotIt)
    #expect(!t.model.cards.contains { $0.id.hasPrefix("newdeal-") })
}
@MainActor @Test func storeDealPopsAsSuggestionAndIsAnnouncedOnce() async throws {
    let t = try make()
    await t.backend.removeDeal(id: "d-parm-3off")            // the pitch starts without the parmesan deal
    await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s"); t.model.ingest(cart: t.backend.cart)
    #expect(t.model.visibleCard?.id == "deal-d-baguette-1off")
    t.voice.sent.removeAll(); t.sounds.played.removeAll()
    t.clock.now += 30
    await t.backend.pushDeal(Deal(id: "d-parm-3off", productId: "kirkland-parmesan", type: .amountOff, value: 3, label: "$3 off",
                                  pairsWith: ["barilla-spaghetti", "rao-marinara"], endsAt: nil))
    t.model.ingest(catalog: t.backend.catalog)                // catalog realtime lands first
    t.model.ingest(cart: t.backend.cart)                      // then the replaced suggestion
    t.model.flushDealAnnouncements(now: t.clock.now + 2)
    #expect(t.voice.sent.filter { if case .suggestion = $0 { true } else { false } }.count == 1)
    #expect(!t.voice.sent.contains { if case .dealChanged = $0 { true } else { false } })
    #expect(t.sounds.played == [.card] && t.model.visibleCard?.id == "deal-d-parm-3off")
    #expect(t.model.reaction?.reaction == .happyBounce)
}
@MainActor @Test func payBlockedUntilItemsConfirmed() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.3, label: "umbrella"); await t.model.beginCheckout()
    await t.model.pay()
    #expect(t.payment.calls == 0 && t.model.highlightUnresolved && t.model.paymentState == .idle)
}
@MainActor @Test func payTwiceChargesOnce() async throws {
    let t = try make(delay: .milliseconds(50)); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b"); await t.model.beginCheckout()
    async let a: Void = t.model.pay(); async let b: Void = t.model.pay(); _ = await (a, b)
    #expect(t.payment.calls == 1)
    guard case .done(let r) = t.model.paymentState else { Issue.record("not done"); return }
    #expect(r.total == Decimal(string: "1.49") && t.model.screen == .receipt && t.sounds.played.last == .success)
    #expect(t.model.reaction?.reaction == .celebrate)
}
@MainActor @Test func paidTellsKartSoItCanSayGoodbye() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b"); await t.model.beginCheckout()
    await t.model.pay()
    #expect(t.voice.sent.last == .uiAction("paid"))
}
@MainActor @Test func declinedPaymentDoesNotTellKartItsPaid() async throws {
    let t = try make(); t.payment.result = .failure(PaymentError.declined); await t.model.startTrip()
    await t.model.beginCheckout(); await t.model.pay()
    #expect(!t.voice.sent.contains(.uiAction("paid")))
}
@MainActor @Test func unsureItemTellsKartOnce() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.3, label: "umbrella")
    t.model.ingest(events: t.backend.events); t.model.ingest(events: t.backend.events)
    #expect(t.voice.sent.filter { $0 == .uiAction("unknown_item") }.count == 1)
}
@MainActor @Test func failedPaymentStaysInCheckout() async throws {
    let t = try make(); t.payment.result = .failure(PaymentError.declined); await t.model.startTrip()
    await t.model.beginCheckout(); await t.model.pay()
    #expect(t.model.paymentState == .failed("Payment didn't go through. Try again.") && t.backend.cart.status == .checkout)
}
@MainActor @Test func startTripClearsStaleState() async throws {
    let t = try make(); t.payment.result = .failure(PaymentError.declined); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.3, label: "jar")
    await t.model.respond(to: try #require(t.model.visibleCard), with: .remove)
    await t.model.beginCheckout(); await t.model.pay()
    await t.model.startTrip()
    #expect(t.model.paymentState == .idle && t.model.cards.isEmpty && !t.model.highlightUnresolved)
}
@MainActor @Test func finishTripStopsVoice() async throws {
    let t = try make(); await t.model.startTrip(); await t.model.finishTrip()
    #expect(t.backend.cart.status == .idle && t.voice.stopCount == 1 && t.model.screen == .welcome)
}
@MainActor @Test func stillShoppingPromptAfterTenQuietMinutes() async throws {
    let t = try make(); await t.model.startTrip(); let t0 = t.clock.now
    #expect(!t.model.stillShoppingPromptDue(now: t0 + 599))
    #expect(t.model.stillShoppingPromptDue(now: t0 + 600))
    t.clock.now = t0 + 300; t.model.noteActivity()
    #expect(!t.model.stillShoppingPromptDue(now: t0 + 899))
}

@MainActor @Test func resumeTripAdoptsStateSilently() async throws {
    let t = try make()
    try await t.backend.startTrip()                            // trip started outside the model (scenario, app relaunch)
    try await t.backend.setPlan(DemoScript.pastaPlan)
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.3, label: "jar")
    t.model.resumeTrip()
    t.model.ingest(cart: t.backend.cart); t.model.ingest(events: t.backend.events); t.model.ingest(catalog: t.backend.catalog)
    t.model.flushDealAnnouncements(now: t.clock.now + 2)
    #expect(t.sounds.played.isEmpty && t.voice.sent.isEmpty)   // nothing re-announced
    #expect(!t.model.cards.contains { $0.id.hasPrefix("newdeal-") })
    #expect(t.model.cards.map(\.id).first == "confirm-2")       // still-open cards still show
}

@MainActor @Test func plannedProductSuggestionIsNotAnnounced() async throws {
    let t = try make(); await t.model.startTrip()
    try await t.backend.setPlan([PlanItem(productId: "kirkland-parmesan", reason: "pasta dinner"),
                                 PlanItem(productId: "french-baguette", reason: "pasta dinner")]); t.model.ingest(cart: t.backend.cart)
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s"); t.model.ingest(cart: t.backend.cart)
    #expect(t.backend.cart.suggestion == nil)
    #expect(!t.voice.sent.contains { if case .suggestion = $0 { true } else { false } })
    #expect(!t.sounds.played.contains(.card) && t.model.visibleCard == nil)
}

// MARK: Final-review fixes

@MainActor @Test func outsideTripResetClearsPaymentAndLocalState() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b"); t.model.ingest(cart: t.backend.cart)
    await t.model.beginCheckout(); await t.model.pay()
    guard case .done = t.model.paymentState else { Issue.record("first trip didn't pay"); return }
    try await t.backend.startTrip()                          // reset from the laptop (cart.py reset / reset-demo)
    t.model.ingest(cart: t.backend.cart)
    #expect(t.model.paymentState == .idle && t.model.celebration == nil && !t.model.highlightUnresolved)
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b")
    await t.model.beginCheckout(); await t.model.pay()
    #expect(t.payment.calls == 2)                            // the next shopper can pay
}

@MainActor @Test func tripResetDuringPaymentDoesNotChargeTheNewTrip() async throws {
    let t = try make(delay: .milliseconds(150)); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: "bananas", confidence: 0.9, label: "b"); t.model.ingest(cart: t.backend.cart)
    await t.model.beginCheckout()
    async let paying: Void = t.model.pay()
    try? await Task.sleep(for: .milliseconds(30))
    try await t.backend.startTrip(); t.model.ingest(cart: t.backend.cart)
    await paying
    #expect(t.backend.receipt == nil && t.backend.cart.status == .shopping && t.model.paymentState == .idle)
}

@MainActor @Test func aFailedConfirmKeepsTheCard() async throws {
    let t = try make(); await t.model.startTrip()
    await t.backend.simulateVision(.added, productId: nil, confidence: 0.3, label: "jar of rao's marinara")
    let card = try #require(t.model.visibleCard)
    await t.model.respond(to: card, with: .choose(productId: "no-such-product"))   // the backend rejects it
    #expect(t.model.unresolvedCount == 1 && t.model.visibleCard?.id == card.id)
}

// MARK: Quantity nudges (beta)

@MainActor @Test func theNudgeCardKeepsItAndKartSaysItOnce() async throws {
    let t = try make(); try await t.backend.setFeature("quantity_nudges", on: true); await t.model.startTrip()
    try await t.backend.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1)]); t.model.ingest(cart: t.backend.cart)
    for _ in 0..<2 { await t.backend.simulateVision(.added, productId: "ground-beef", confidence: 0.9, label: "b"); t.model.ingest(cart: t.backend.cart) }
    t.model.ingest(cart: t.backend.cart)
    let card = try #require(t.model.visibleCard)
    #expect(card.title == "That's your 2nd Ground Beef. Your list says 1. Keep it?" && card.actions == [.keepIt, .gotIt])
    #expect(t.voice.sent.filter { if case .nudge = $0 { true } else { false } }.count == 1)
    await t.model.respond(to: card, with: .keepIt)
    #expect(t.backend.cart.plan.first?.qty == 2 && t.backend.cart.nudge == nil)
}

@MainActor @Test func noNudgeCardWithTheFlagOff() async throws {
    let t = try make(); await t.model.startTrip()
    try await t.backend.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 1)])
    for _ in 0..<2 { await t.backend.simulateVision(.added, productId: "ground-beef", confidence: 0.9, label: "b") }
    t.model.ingest(cart: t.backend.cart)
    #expect(t.model.visibleCard == nil && !t.voice.sent.contains { if case .nudge = $0 { true } else { false } })
}

@MainActor @Test func plusAndMinusFixAMiscount() async throws {
    let t = try make(); await t.model.startTrip()
    await t.model.adjust("ground-beef", by: 1)
    await t.model.adjust("ground-beef", by: 1)
    await t.model.adjust("ground-beef", by: -1)
    #expect(t.backend.cart.items.map { ($0.productId, $0.qty) }.first.map { $0 == ("ground-beef", 1) } == true)
    #expect(t.backend.events.allSatisfy { $0.source == .manual })
}

// MARK: One cart change, one announcement (on-device: realtime bursts, out-of-order refetches, a second screen)

@MainActor @Test func aStaleOrReplayedCartStateAnnouncesNothingTwice() async throws {
    let t = try make(); await t.model.startTrip(); t.model.ingest(cart: t.backend.cart)
    let before = t.backend.cart
    t.clock.now += 1
    await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "s")   // + parmesan deal
    let after = t.backend.cart
    t.model.ingest(cart: after)
    t.model.ingest(cart: before)                                // an older refetch lands late
    t.model.ingest(cart: after)
    var gap = after; gap.suggestion = nil; gap.updatedAt = after.updatedAt?.addingTimeInterval(1)
    var back = after; back.updatedAt = after.updatedAt?.addingTimeInterval(2)
    t.model.ingest(cart: gap); t.model.ingest(cart: back)       // the same deal, after a moment without it
    let sent = t.voice.sent
    #expect(sent.filter { if case .cartChanged(.added) = $0 { true } else { false } }.count == 1)
    #expect(sent.filter { if case .cartChanged(.removed) = $0 { true } else { false } }.isEmpty)
    #expect(sent.filter { if case .suggestion = $0 { true } else { false } }.count == 1)
    #expect(t.sounds.played.filter { $0 == .added }.count == 1)
}

@MainActor @Test func atCheckoutTheShortNudgeOffersGoGetItOrSkipIt() async throws {
    let t = try make(); try await t.backend.setFeature("quantity_nudges", on: true); await t.model.startTrip()
    try await t.backend.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 2)])
    await t.backend.simulateVision(.added, productId: "ground-beef", confidence: 0.9, label: "b")
    await t.model.beginCheckout(); t.model.ingest(cart: t.backend.cart)
    let card = try #require(t.model.cards.first { if case .nudge = $0.kind { true } else { false } })
    #expect(card.actions == [.goGetIt, .skipIt])
    await t.model.respond(to: card, with: .goGetIt)                 // back to the aisle, the nudge acknowledged
    #expect(t.backend.cart.status == .shopping && t.backend.cart.nudge == nil)
}


@MainActor @Test func theCheckoutListCardNamesTheAislesWithGoGetThemOrSkip() async throws {
    let t = try make(); try await t.backend.setFeature("quantity_nudges", on: true); await t.model.startTrip()
    try await t.backend.setPlan([PlanItem(productId: "ground-beef", reason: "tacos", qty: 2),
                                 PlanItem(productId: "tostitos-salsa", reason: "tacos")])
    await t.backend.simulateVision(.added, productId: "ground-beef", confidence: 0.9, label: "b")
    await t.model.beginCheckout(); t.model.ingest(cart: t.backend.cart)
    let card = try #require(t.model.cards.first { if case .nudge = $0.kind { true } else { false } })
    #expect(card.title == "Before you go: you still need Ground Beef (Aisle 3) and Salsa (Aisle 5).")
    #expect(card.actions == [.goGetThem, .skip])
    await t.model.respond(to: card, with: .skip)
    #expect(t.backend.cart.nudge == nil && t.backend.cart.status == .checkout)
}


@MainActor @Test func aQuietCartPausesKartsVoiceAfterThreeMinutes() async throws {
    let t = try make(); await t.model.startTrip()
    t.clock.now += 179; t.model.pauseVoiceIfQuiet(now: t.clock.now)
    #expect(t.voice.pauseCount == 0)
    t.clock.now += 2; t.model.pauseVoiceIfQuiet(now: t.clock.now)
    #expect(t.voice.pauseCount == 1)                          // no call minutes while nobody's shopping
}
@MainActor @Test func aRecentConversationKeepsTheCallOpen() async throws {
    let t = try make(); await t.model.startTrip()
    t.clock.now += 181; t.voice.lastActiveAt = t.clock.now - 30   // Kart and the shopper talked half a minute ago
    t.model.pauseVoiceIfQuiet(now: t.clock.now)
    #expect(t.voice.pauseCount == 0)
}
@MainActor @Test func aTapWakesAPausedKart() async throws {
    let t = try make(); await t.model.startTrip()
    t.voice.state = .paused
    t.model.noteActivity(); await settle()
    #expect(t.voice.resumeCount == 1)
}
@MainActor @Test func voiceComesBackOnItsOwnWhenTheNetworkDoes() async throws {
    let t = try make(); await t.model.startTrip()
    t.voice.state = .offline
    await t.model.networkRestored()
    #expect(t.voice.startCount == 2)
    t.voice.state = .listening
    await t.model.networkRestored()                            // already talking: nothing to do
    #expect(t.voice.startCount == 2)
}
