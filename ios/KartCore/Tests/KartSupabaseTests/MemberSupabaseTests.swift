import Foundation
import Testing
@testable import KartCore
@testable import KartSupabase

private let memberProfileJSON = """
{"member": {"member_id": "1029", "name": "Dylan", "household": 4, "since": "2026-08-14", "trips": 15},
 "today": "2026-10-24", "weekday": "Saturday", "picks": [], "usuals": [], "memories": [], "last_trip": null}
"""

/// Member memory over Supabase (contract v0.14, beta). In the PostgREST suite: StubProtocol's state is shared.
extension PostgRESTTests {
    static func cartRow(member: String?, rev: Int = 0) -> String {
        let id = member.map { "\"\($0)\"" } ?? "null"
        return #"[{"cart_id": "7", "trip_id": "6f9619ff-8b86-d011-b42d-00c04fc964ff", "status": "shopping", "member_id": \#(id), "member_rev": \#(rev), "features": {"member_memory": true}}]"#
    }

    @MainActor func memberBackend() throws -> SupabaseKartBackend {
        SupabaseKartBackend(url: URL(string: "http://127.0.0.1:54321")!, anonKey: "anon", cartId: "7",
                            layout: try Fixtures.catalog().layout, session: StubProtocol.session())
    }

    @MainActor @Test func signInPostsSetMemberThenLoadsTheProfile() async throws {
        StubProtocol.routes = ["set_member": .init(status: 200, body: "{}"),
                               "carts": .init(status: 200, body: Self.cartRow(member: "1029")),
                               "member_profile": .init(status: 200, body: memberProfileJSON)]
        defer { StubProtocol.routes = [:] }
        let backend = try memberBackend()
        try await backend.signIn(memberId: "1029")
        #expect(backend.cart.memberId == "1029" && backend.memberProfile?.member.name == "Dylan")
        let body = try JSONSerialization.jsonObject(with: try #require(StubProtocol.lastBody)) as? [String: String]
        #expect(StubProtocol.lastRequest?.url?.lastPathComponent == "member_profile")
        #expect(body == ["p_member_id": "1029", "p_cart_id": "7"])
    }

    @MainActor @Test func featureOffMapsToError() async throws {
        StubProtocol.routes = ["set_member": .init(status: 400, body: #"{"message": "feature_off: member_memory", "code": "P0001"}"#)]
        defer { StubProtocol.routes = [:] }
        let backend = try memberBackend()
        await #expect(throws: KartBackendError.featureOff) { try await backend.signIn(memberId: "1029") }
    }

    @MainActor @Test func memberRevChangeRefetchesProfile() async throws {
        StubProtocol.routes = ["carts": .init(status: 200, body: Self.cartRow(member: "1029")),
                               "member_profile": .init(status: 200, body: memberProfileJSON)]
        defer { StubProtocol.routes = [:] }
        let backend = try memberBackend()
        try await backend.startTrip()
        #expect(backend.memberProfile?.member.name == "Dylan")
        StubProtocol.routes["carts"] = .init(status: 200, body: Self.cartRow(member: "1029", rev: 1))
        StubProtocol.routes["member_profile"] = .init(status: 200, body: memberProfileJSON.replacingOccurrences(of: "\"Dylan\"", with: "\"Dyl\""))
        try await backend.startTrip()
        #expect(backend.memberProfile?.member.name == "Dyl")
        StubProtocol.routes["carts"] = .init(status: 200, body: Self.cartRow(member: nil, rev: 1))
        try await backend.startTrip()
        #expect(backend.memberProfile == nil)
    }
}
