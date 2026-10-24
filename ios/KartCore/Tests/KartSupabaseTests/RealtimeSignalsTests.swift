import Foundation
import Testing
@testable import KartSupabase

@Test func joinMessageSubscribesToPostgresChanges() throws {
    let text = RealtimeSignals.joinMessage(topic: "realtime:kart-carts-cart_id-eq-7", table: "carts", filter: "cart_id=eq.7",
                                           anonKey: "anon", ref: "1")
    let message = try #require(try JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any])
    #expect(message["event"] as? String == "phx_join" && message["topic"] as? String == "realtime:kart-carts-cart_id-eq-7")
    let payload = try #require(message["payload"] as? [String: Any])
    #expect(payload["access_token"] as? String == "anon")
    let changes = try #require((payload["config"] as? [String: Any])?["postgres_changes"] as? [[String: Any]])
    #expect(changes.first?["table"] as? String == "carts" && changes.first?["filter"] as? String == "cart_id=eq.7")
    #expect(changes.first?["event"] as? String == "*" && changes.first?["schema"] as? String == "public")
}

@Test func topicsAreStableAndDistinctPerFilter() {
    #expect(RealtimeSignals.topic(table: "products", filter: nil) == "realtime:kart-products")
    #expect(RealtimeSignals.topic(table: "carts", filter: "cart_id=eq.7") != RealtimeSignals.topic(table: "carts", filter: "cart_id=eq.8"))
}

@Test func classifiesServerMessages() {
    func data(_ s: String) -> Data { Data(s.utf8) }
    #expect(RealtimeSignals.classify(data(#"{"topic":"realtime:kart-carts","event":"system","payload":{"status":"ok","message":"Subscribed to PostgreSQL","extension":"postgres_changes"},"ref":null}"#))
            == .subscribed(topic: "realtime:kart-carts"))
    #expect(RealtimeSignals.classify(data(#"{"topic":"realtime:kart-carts","event":"postgres_changes","payload":{"data":{"type":"UPDATE","record":{}}},"ref":null}"#))
            == .change(topic: "realtime:kart-carts"))
    #expect(RealtimeSignals.classify(data(#"{"topic":"realtime:kart-carts","event":"phx_reply","payload":{"status":"error","response":{"reason":"bad"}},"ref":"1"}"#))
            == .joinError(topic: "realtime:kart-carts", reason: "bad"))
    #expect(RealtimeSignals.classify(data(#"{"topic":"phoenix","event":"phx_reply","payload":{"status":"ok","response":{}},"ref":"2"}"#)) == .other)
    #expect(RealtimeSignals.classify(data("not json")) == .other)
}
