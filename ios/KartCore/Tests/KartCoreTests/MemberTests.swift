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
