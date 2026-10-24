import Foundation
import Testing
@testable import KartCore

/// Member memory (contract v0.14, beta): the models, the cart's member fields, and what the agent hears.
struct MemberContractTests {
    @Test func profileDecodesBackendJSON() throws {
        let p = try KartJSON.decoder().decode(MemberProfile.self, from: Data(Fixtures.memberProfileJSON.utf8))
        #expect(p.member.name == "Dylan" && p.member.trips == 15 && p.weekday == "Saturday")
        #expect(p.picks.map(\.kind) == [.event, .due])
        #expect(p.picks[0].reason == "Leo's soccer party · tomorrow" && p.picks[0].memoryId == 16)
        #expect(p.usuals.first?.everyDays == 7)
        let party = try #require(p.memories.first)
        #expect(party.isUpcoming && party.title == "Leo's soccer party" && party.items?.first?.qty == 1)
        #expect(!p.memories[1].isUpcoming && p.memories[1].items == nil)
        #expect(p.lastTrip?.items == ["Milk", "Tortillas"] && p.lastTrip?.total == Decimal(string: "51.2"))
    }

    @Test func cartDecodesMemberFieldsWithDefaults() throws {
        let row = #"{"cart_id": "7", "member_id": "1029", "member_rev": 3, "demo_date": "2026-10-30", "features": {"member_memory": true}}"#
        let cart = try KartJSON.decoder().decode(CartState.self, from: Data(row.utf8))
        #expect(cart.memberId == "1029" && cart.memberRev == 3 && cart.demoDate == "2026-10-30" && cart.memberMemoryOn)
        let bare = try KartJSON.decoder().decode(CartState.self, from: Data(#"{"cart_id": "7"}"#.utf8))
        #expect(bare.memberId == nil && bare.memberRev == 0 && bare.demoDate == nil && !bare.memberMemoryOn)
    }

    @Test func tripContextMetadataIncludesMemberOnlyWhenSet() {
        let trip = UUID(uuidString: "6F9619FF-8B86-D011-B42D-00C04FC964FF")!
        #expect(LineCodec.metadata(.tripContext(cartId: "7", tripId: trip, memberId: "1029"))["member_id"] as? String == "1029")
        #expect(LineCodec.metadata(.tripContext(cartId: "7", tripId: trip))["member_id"] == nil)
    }

    @Test func lullMetadata() {
        #expect(LineCodec.metadata(.lull)["type"] as? String == "lull")
    }
}

/// The mock imitates the backend's member memory, so the offline demo mode rehearses the whole beat.
@MainActor struct MockMemberTests {
    /// Saturday 2026-10-24, noon in the store's time zone.
    let clock = ManualClock(now: Date(timeIntervalSince1970: 1_792_868_400))

    func backend(flag: Bool = true) async throws -> MockKartBackend {
        let b = MockKartBackend(catalog: try Fixtures.catalog(), clock: { [clock] in clock.now })
        if flag { try await b.setFeature("member_memory", on: true) }
        try await b.startTrip()
        return b
    }

    func picks(_ b: MockKartBackend) -> [[String]] {
        (b.memberProfile?.picks ?? []).map { [$0.productId, $0.kind.rawValue, $0.reason] }
    }

    @Test func signInNeedsFlag() async throws {
        let b = try await backend(flag: false)
        await #expect(throws: KartBackendError.featureOff) { try await b.signIn(memberId: "1029") }
        #expect(b.cart.memberId == nil && b.memberProfile == nil)
    }

    @Test func profilePicksForDylan() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "1029")
        #expect(b.cart.memberId == "1029" && b.memberProfile?.member.name == "Dylan")
        #expect(b.memberProfile?.weekday == "Saturday" && b.memberProfile?.today == "2026-10-24")
        #expect(picks(b) == [["barilla-spaghetti", "event", "Leo's soccer party · tomorrow"],
                             ["whole-milk", "due", "every week · last Sat"],
                             ["mission-tortillas", "usual", "your Saturday usual"]])
    }

    @Test func startTripClearsMember() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "1029")
        try await b.startTrip()
        #expect(b.cart.memberId == nil && b.memberProfile == nil)
    }

    @Test func fastForwardShowsSavedEventAndDueMilk() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "1029")
        try await b.remember(kind: "event", text: "Friendsgiving for 10", eventDate: "2026-10-31",
                             items: [PlanItem(productId: "barilla-spaghetti", reason: "Friendsgiving", qty: 3)])
        try await b.applyManualEvent(.added, productId: "whole-milk", resolving: nil)
        _ = try await b.checkout(provider: "simulated")
        try await b.setDemoDate("2026-10-30")
        try await b.startTrip()
        try await b.signIn(memberId: "1029")
        #expect(b.memberProfile?.today == "2026-10-30")
        #expect(picks(b).first == ["barilla-spaghetti", "event", "Friendsgiving for 10 · tomorrow"])
        #expect(picks(b).contains(["whole-milk", "due", "every week · last Sat"]))
        #expect(b.memberProfile?.memories.first { $0.title == "Leo's soccer party" }?.isPast == true)
    }

    @Test func unknownNumberIsANewMember() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "4321")
        #expect(b.memberProfile?.member.name == nil && b.memberProfile?.member.trips == 0 && picks(b).isEmpty)
    }

    @Test func forgetAllSignsOut() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "1029")
        try await b.forgetMember()
        #expect(b.cart.memberId == nil && b.memberProfile == nil)
        try await b.signIn(memberId: "1029")
        #expect(b.memberProfile?.member.name == nil && b.memberProfile?.memories.isEmpty == true)
    }

    @Test func forgetOneMemory() async throws {
        let b = try await backend()
        try await b.signIn(memberId: "1029")
        let party = try #require(b.memberProfile?.memories.first)
        let rev = b.cart.memberRev
        try await b.forgetMemory(id: party.id)
        #expect(b.memberProfile?.memories.contains { $0.id == party.id } == false && b.cart.memberRev == rev + 1)
    }
}

/// What the screen does with member memory: sign-in order, For you, the lull, the demo date.
@MainActor struct AppModelMemberTests {
    func rig(flag: Bool = true) async throws -> TestRig {
        let t = try make()
        t.clock.now = Date(timeIntervalSince1970: 1_792_868_400)       // Saturday 2026-10-24, noon (store time)
        if flag { try await t.backend.setFeature("member_memory", on: true) }
        return t
    }

    @Test func signInThenTripContextCarriesMember() async throws {
        let t = try await rig()
        await t.model.startTrip(memberId: "1029")
        #expect(t.backend.cart.memberId == "1029" && t.model.member?.member.name == "Dylan")
        #expect(t.voice.sent.first == .tripContext(cartId: "7", tripId: try #require(t.backend.cart.tripId), memberId: "1029"))
    }

    @Test func signInWithFlagOffStartsGuestTrip() async throws {
        let t = try await rig(flag: false)
        await t.model.startTrip(memberId: "1029")
        #expect(t.backend.cart.memberId == nil && t.model.member == nil && t.model.screen != .welcome)
        #expect(t.voice.sent.first == .tripContext(cartId: "7", tripId: try #require(t.backend.cart.tripId)))
    }

    @Test func lullOnceAfter40sNotWithCard() async throws {
        let t = try await rig()
        await t.model.startTrip(memberId: "1029")
        t.clock.now += 39
        #expect(!t.model.lullDue(now: t.clock.now))
        await t.backend.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.9, label: "spaghetti")
        t.clock.now += 41
        #expect(t.model.visibleCard != nil && !t.model.lullDue(now: t.clock.now))   // a deal card is up
        try await t.backend.dismissSuggestion()
        #expect(t.model.visibleCard == nil && t.model.lullDue(now: t.clock.now))
        t.model.sendLullIfDue(now: t.clock.now)
        t.model.sendLullIfDue(now: t.clock.now + 60)
        #expect(t.voice.sent.filter { $0 == .lull }.count == 1)
    }

    @Test func lullNeverForGuests() async throws {
        let t = try await rig()
        await t.model.startTrip()
        #expect(!t.model.lullDue(now: t.clock.now + 600))
    }

    @Test func forYouHidesPicksOnPlanAndAfterDismiss() async throws {
        let t = try await rig()
        await t.model.startTrip(memberId: "1029")
        #expect(t.model.forYouPicks.map(\.productId) == ["barilla-spaghetti", "whole-milk", "mission-tortillas"])
        try await t.backend.setPlan([PlanItem(productId: "whole-milk", reason: "milk")])
        #expect(t.model.forYouPicks.map(\.productId) == ["barilla-spaghetti", "mission-tortillas"])
        await t.model.addPick(t.model.forYouPicks[0])
        #expect(t.backend.cart.plan.contains { $0.productId == "barilla-spaghetti" && $0.reason == "for you" })
        t.model.dismissForYou()
        #expect(t.model.forYouPicks.isEmpty && t.model.savedEvent == nil)
    }

    @Test func shopSavedListAppendsItems() async throws {
        let t = try await rig()
        await t.model.startTrip(memberId: "1029")
        try await t.backend.setPlan([PlanItem(productId: "whole-milk", reason: "milk")])
        let party = try #require(t.model.savedEvent)
        #expect(party.title == "Leo's soccer party")
        await t.model.shopSavedList(party)
        #expect(t.backend.cart.plan.map(\.productId) == ["whole-milk", "barilla-spaghetti", "rao-marinara", "french-baguette"])
        #expect(t.backend.cart.plan.last?.reason == "Leo's soccer party" && t.model.savedEvent == nil)
    }

    @Test func demoJumpDayBeforeNextEvent() async throws {
        let t = try await rig()
        await t.model.startTrip(memberId: "1029")
        #expect(!t.model.dayBeforeNextEventAvailable)                  // Leo's party is tomorrow: nothing to jump to
        try await t.backend.remember(kind: "event", text: "Friendsgiving for 10", eventDate: "2026-10-31", items: [])
        #expect(t.model.dayBeforeNextEventAvailable && t.model.nextEventTitle == "Friendsgiving for 10")
        await t.model.jumpDemoDate(to: .dayBeforeNextEvent)
        #expect(t.backend.cart.demoDate == "2026-10-30")
        await t.model.jumpDemoDate(to: .plusDays(1))
        #expect(t.backend.cart.demoDate == "2026-10-31")
        await t.model.jumpDemoDate(to: .today)
        #expect(t.backend.cart.demoDate == nil)
    }

    @Test func demoDateLabel() async throws {
        let t = try await rig()
        #expect(t.model.demoDateLabel == nil)
        try await t.backend.setDemoDate("2026-10-30")
        #expect(t.model.demoDateLabel == "Fri, Oct 30 · demo date")
    }
}

@MainActor @Test func memberScenariosSeedTheBeat() async throws {
    func run(_ s: DemoScenario) async throws -> MockKartBackend {
        let clock = ManualClock()
        let b = MockKartBackend(catalog: try Fixtures.catalog(), clock: { clock.now })
        try await s.apply(to: b, clock: clock)
        return b
    }
    let welcome = try await run(.memberWelcome)
    #expect(welcome.cart.status == .idle && welcome.cart.memberMemoryOn)
    let member = try await run(.member)
    #expect(member.cart.memberId == "1029" && member.memberProfile?.picks.count == 3)
    #expect(member.transcript.contains { $0.text.hasPrefix("Welcome back, Dylan!") })
    #expect(TripRouter.screen(cart: member.cart, transcript: member.transcript) == .shopping)
}
