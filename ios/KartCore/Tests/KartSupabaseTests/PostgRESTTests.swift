import Foundation
import Testing
@testable import KartCore
@testable import KartSupabase

/// Serves canned responses and records what was sent.
final class StubProtocol: URLProtocol, @unchecked Sendable {
    struct Reply: Sendable { var status: Int; var body: String }
    nonisolated(unsafe) static var reply = Reply(status: 200, body: "[]")
    nonisolated(unsafe) static var lastRequest: URLRequest?
    nonisolated(unsafe) static var lastBody: Data?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.lastRequest = request
        Self.lastBody = request.httpBody ?? request.httpBodyStream.map { stream in
            stream.open(); defer { stream.close() }
            var data = Data(); var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable { let n = stream.read(&buffer, maxLength: buffer.count); if n <= 0 { break }; data.append(buffer, count: n) }
            return data
        }
        let response = HTTPURLResponse(url: request.url!, statusCode: Self.reply.status, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(Self.reply.body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}

    static func session() -> URLSession {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [StubProtocol.self]
        return URLSession(configuration: config)
    }
}

@Suite(.serialized) struct PostgRESTTests {
    let rest = PostgREST(url: URL(string: "http://127.0.0.1:54321")!, anonKey: "anon-key", session: StubProtocol.session())

    @Test func selectSendsAuthAndDecodesWithKartJSON() async throws {
        StubProtocol.reply = .init(status: 200, body: #"[{"id":"A1","name":"Aisle 1 · Produce","x":2,"y":1,"w":1,"h":8}]"#)
        let rows: [KartCore.Section] = try await rest.select("sections?select=*&order=id")
        #expect(rows.first?.aisleLabel == "Aisle 1")
        let request = try #require(StubProtocol.lastRequest)
        #expect(request.url?.absoluteString == "http://127.0.0.1:54321/rest/v1/sections?select=*&order=id")
        #expect(request.value(forHTTPHeaderField: "apikey") == "anon-key")
        #expect(request.value(forHTTPHeaderField: "Authorization") == "Bearer anon-key")
        #expect(request.httpMethod == "GET")
    }

    @Test func rpcPostsNamedParameters() async throws {
        StubProtocol.reply = .init(status: 200, body: "{}")
        try await rest.rpc("set_cart_status", ["p_cart_id": "7", "p_status": "checkout", "p_resolves_event_id": nil])
        let request = try #require(StubProtocol.lastRequest)
        #expect(request.url?.path == "/rest/v1/rpc/set_cart_status" && request.httpMethod == "POST")
        let body = try JSONSerialization.jsonObject(with: try #require(StubProtocol.lastBody)) as? [String: Any]
        #expect(body?["p_cart_id"] as? String == "7" && body?["p_status"] as? String == "checkout")
        #expect(body?["p_resolves_event_id"] is NSNull)
    }

    @Test func errorsCarryTheMessageAndUnresolvedCount() async throws {
        StubProtocol.reply = .init(status: 400, body: #"{"code":"P0001","details":null,"hint":null,"message":"unresolved_items: 2 item(s) need confirming"}"#)
        do {
            try await rest.rpc("checkout", ["p_cart_id": "7", "p_provider": "simulated"])
            Issue.record("expected an error")
        } catch let error as PostgRESTError {
            #expect(error.status == 400 && error.code == "P0001")
            #expect(error.unresolvedCount == 2)
        }
        #expect(PostgRESTError(status: 400, message: "permission denied", code: "42501").unresolvedCount == nil)
    }

    @MainActor @Test func backendSurfacesRowsItCannotDecode() async throws {
        StubProtocol.reply = .init(status: 200, body: "{}")          // reset_cart is fine; a carts read of {} isn't an array
        let backend = SupabaseKartBackend(url: URL(string: "http://127.0.0.1:54321")!, anonKey: "anon", cartId: "7",
                                          layout: try Fixtures.catalog().layout, session: StubProtocol.session())
        #expect(backend.lastError == nil)
        try await backend.startTrip()
        #expect(backend.lastError?.contains("carts") == true)
    }

    @MainActor @Test func aLateOlderRefetchNeverStepsTheCartBack() async throws {
        let trip = "6f9619ff-8b86-d011-b42d-00c04fc964ff"
        func row(_ updated: String, qty: Int) -> String {
            #"[{"cart_id":"7","trip_id":"\#(trip)","status":"shopping","updated_at":"\#(updated)","#
                + #""items":[{"product_id":"bananas","name":"Bananas","price":1.49,"qty":\#(qty),"added_at":"2026-10-24T18:00:00Z"}]}]"#
        }
        let backend = SupabaseKartBackend(url: URL(string: "http://127.0.0.1:54321")!, anonKey: "anon", cartId: "7",
                                          layout: try Fixtures.catalog().layout, session: StubProtocol.session())
        StubProtocol.reply = .init(status: 200, body: row("2026-10-24T18:00:02Z", qty: 2))
        try await backend.dismissSuggestion()                       // any RPC refetches the cart
        #expect(backend.cart.items.first?.qty == 2)
        StubProtocol.reply = .init(status: 200, body: row("2026-10-24T18:00:01Z", qty: 1))   // an older read lands late
        try await backend.dismissSuggestion()
        #expect(backend.cart.items.first?.qty == 2)
    }
}
