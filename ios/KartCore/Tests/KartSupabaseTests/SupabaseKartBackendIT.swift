import Foundation
import Testing
@testable import KartCore
@testable import KartSupabase

/// Live tests against a running Supabase (local stack). Run with:
///   KART_IT=1 SUPABASE_URL=… SUPABASE_ANON_KEY=… swift test --filter KartSupabaseTests
/// They use their own cart (`ios-it-<random>`) so they never touch the demo cart 7.
private let env = ProcessInfo.processInfo.environment
private let live = env["KART_IT"] == "1" && env["SUPABASE_URL"] != nil && env["SUPABASE_ANON_KEY"] != nil

@MainActor
private func waitUntil(_ timeout: Duration = .seconds(5), _ condition: () -> Bool) async -> Bool {
    let deadline = ContinuousClock.now + timeout
    while ContinuousClock.now < deadline {
        if condition() { return true }
        try? await Task.sleep(for: .milliseconds(100))
    }
    return condition()
}

@Suite(.serialized, .enabled(if: live))
@MainActor struct SupabaseKartBackendIT {
    let url = URL(string: env["SUPABASE_URL"] ?? "http://127.0.0.1:54321")!
    let key = env["SUPABASE_ANON_KEY"] ?? ""

    func backend(_ cartId: String) throws -> SupabaseKartBackend {
        SupabaseKartBackend(url: url, anonKey: key, cartId: cartId, layout: try Fixtures.catalog().layout)
    }

    @Test func fullTripThroughTheRPCs() async throws {
        let cartId = "ios-it-\(UUID().uuidString.prefix(8).lowercased())"
        let b = try backend(cartId)
        await b.start()
        defer { b.stop() }
        #expect(await waitUntil { !b.catalog.products.isEmpty })
        try await b.startTrip()
        #expect(b.cart.status == .shopping && b.cart.tripId != nil)

        try await b.setPlan(DemoScript.pastaPlan)
        #expect(b.cart.plan.count == 4 && b.cart.plan.allSatisfy { $0.aisle != nil })

        await b.simulateVision(.added, productId: "barilla-spaghetti", confidence: 0.95, label: "spaghetti")
        #expect(b.cart.items.map(\.productId) == ["barilla-spaghetti"])
        #expect(b.cart.suggestion != nil)

        await b.simulateVision(.added, productId: nil, confidence: 0.3, label: "red jar of Rao's marinara")
        #expect(b.events.contains { $0.needsConfirmation })
        await #expect(throws: KartBackendError.unresolvedItems(count: 1)) { _ = try await b.checkout(provider: "simulated") }

        let unknown = try #require(b.events.first { $0.needsConfirmation })
        try await b.applyManualEvent(.added, productId: "rao-marinara", resolving: unknown.eventId)
        #expect(!b.events.contains { $0.needsConfirmation })
        #expect(b.cart.items.contains { $0.productId == "rao-marinara" })

        try await b.appendTranscript(.agent, "Got it, Rao's Sauce.")
        #expect(b.transcript.last?.text == "Got it, Rao's Sauce.")

        try await b.setStatus(.checkout)
        let receipt = try await b.checkout(provider: "simulated")
        #expect(receipt.status == "paid" && b.cart.status == .paid && b.receipt == receipt)
        try await b.endTrip()
        #expect(b.cart.status == .idle)
    }

    @Test func realtimeDeliversOutsideChanges() async throws {
        let cartId = "ios-it-\(UUID().uuidString.prefix(8).lowercased())"
        let b = try backend(cartId)
        await b.start()
        defer { b.stop() }
        #expect(await waitUntil(.seconds(10)) { b.connection == .online })
        try await b.startTrip()
        // Another client (the Pi) adds bananas: write through a separate REST client, not through `b`.
        let pi = PostgREST(url: url, anonKey: key)
        try await pi.rpc("apply_cart_event", [
            "p_cart_id": .string(cartId), "p_type": "added", "p_product_id": "bananas", "p_confidence": 0.9, "p_source": "vision",
            "p_label": "bananas", "p_camera": nil, "p_snapshot_url": nil, "p_event_id": .string(UUID().uuidString.lowercased()),
            "p_method": "local", "p_resolves_event_id": nil,
        ])
        #expect(await waitUntil(.seconds(5)) { b.cart.items.contains { $0.productId == "bananas" } })
        try await b.endTrip()
    }
}
