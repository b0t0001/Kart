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
