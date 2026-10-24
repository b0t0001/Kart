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
        await backend.profileLoad?.value
        #expect(backend.cart.memberId == "1029" && backend.memberProfile?.member.name == "Dylan")
        await backend.refreshMemberProfile()                   // the background read raced the cart's: ask once more
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
        await backend.profileLoad?.value
        #expect(backend.memberProfile?.member.name == "Dylan")
        StubProtocol.routes["carts"] = .init(status: 200, body: Self.cartRow(member: "1029", rev: 1))
        StubProtocol.routes["member_profile"] = .init(status: 200, body: memberProfileJSON.replacingOccurrences(of: "\"Dylan\"", with: "\"Dyl\""))
        try await backend.startTrip()
        await backend.profileLoad?.value
        #expect(backend.memberProfile?.member.name == "Dyl")
        StubProtocol.routes["carts"] = .init(status: 200, body: Self.cartRow(member: nil, rev: 1))
        try await backend.startTrip()
        await backend.profileLoad?.value
        #expect(backend.memberProfile == nil)
    }
}

/// Answers every request at once except `member_profile`, which takes `profileDelay` seconds.
final class SlowProfileStub: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var profileDelay: TimeInterval = 2

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let path = request.url?.lastPathComponent ?? ""
        let body = switch path {
        case "carts": PostgRESTTests.cartRow(member: "1029")
        case "member_profile": memberProfileJSON
        case "cart_events", "transcript", "receipts": "[]"
        default: "{}"
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + (path == "member_profile" ? Self.profileDelay : 0)) { [self] in
            let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
                                           headerFields: ["Content-Type": "application/json"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(body.utf8))
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {}
}

@MainActor @Test func signInDoesNotWaitOnTheProfile() async throws {
    let config = URLSessionConfiguration.ephemeral
    config.protocolClasses = [SlowProfileStub.self]
    let backend = SupabaseKartBackend(url: URL(string: "http://127.0.0.1:54321")!, anonKey: "anon", cartId: "7",
                                      layout: try Fixtures.catalog().layout, session: URLSession(configuration: config))
    let started = Date()
    try await backend.signIn(memberId: "1029")
    #expect(Date().timeIntervalSince(started) < 1 && backend.cart.memberId == "1029")   // the trip starts now
    await backend.profileLoad?.value
    #expect(backend.memberProfile?.member.name == "Dylan")                              // memory arrives after
}
