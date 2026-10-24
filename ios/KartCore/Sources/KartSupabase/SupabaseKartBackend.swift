import Foundation
import KartCore
import Observation

/// The real backend (contract v0.9): REST reads and RPC writes with the anon key, realtime as change signals.
/// Every signal refetches its slice, so a dropped socket or a missed message only costs a refetch.
@MainActor @Observable
public final class SupabaseKartBackend: KartBackend {
    public private(set) var cart: CartState
    public private(set) var events: [CartEvent] = []
    public private(set) var catalog: Catalog
    public private(set) var transcript: [TranscriptLine] = []
    public private(set) var connection: ConnectionState = .reconnecting
    public private(set) var receipt: Receipt?
    /// The last read that failed (network or a row that didn't decode), for the debug panel. Cleared on success.
    public private(set) var lastError: String?

    @ObservationIgnored private let rest: PostgREST
    @ObservationIgnored private let realtime: RealtimeSignals
    @ObservationIgnored private let cartId: String
    @ObservationIgnored private var tasks: [Task<Void, Never>] = []
    @ObservationIgnored private var pending: [Slice: Task<Void, Never>] = [:]

    private enum Slice: Hashable { case cart, events, transcript, receipt, catalog }

    public init(url: URL, anonKey: String, cartId: String, layout: StoreLayout, session: URLSession = .shared) {
        self.rest = PostgREST(url: url, anonKey: anonKey, session: session)
        self.realtime = RealtimeSignals(url: url, anonKey: anonKey, session: session)
        self.cartId = cartId
        self.cart = .empty(cartId: cartId)
        self.catalog = Catalog(layout: layout, products: [], deals: [])
    }

    /// Loads everything, then follows realtime. While realtime isn't confirmed, polls every 5 s.
    public func start() async {
        await refreshCatalog()
        await refreshCart(force: true)
        let filter = "cart_id=eq.\(cartId)"
        let watched: [(String, String?, Slice)] = [
            ("carts", filter, .cart), ("cart_events", filter, .events), ("transcript", filter, .transcript),
            ("receipts", filter, .receipt), ("products", nil, .catalog), ("deals", nil, .catalog),
        ]
        for (table, filter, slice) in watched {
            let signals = await realtime.watch(table: table, filter: filter)
            tasks.append(Task { [weak self] in
                for await _ in signals { self?.schedule(slice) }
            })
        }
        let status = await realtime.statusUpdates()
        tasks.append(Task { [weak self] in
            for await up in status { self?.connection = up ? .online : .reconnecting }
        })
        tasks.append(Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard let self, self.connection == .reconnecting else { continue }
                await self.refreshCart(force: true)
                await self.refreshCatalog()
            }
        })
        await realtime.start()
    }

    public func stop() {
        tasks.forEach { $0.cancel() }
        tasks = []
        Task { await realtime.stop() }
    }

    // MARK: KartBackend intents

    public func startTrip() async throws {
        try await rest.rpc("reset_cart", ["p_cart_id": .string(cartId)])
        await refreshCart(force: true)
    }

    public func applyManualEvent(_ type: CartEventType, productId: String, resolving eventId: UUID?) async throws {
        try await applyEvent(type, productId: productId, source: "manual", method: "manual", confidence: 1, label: nil,
                             resolving: eventId)
    }

    public func resolveUnknown(eventId: UUID) async throws {
        try await applyEvent(.removed, productId: nil, source: "manual", method: "manual", confidence: 1, label: nil,
                             resolving: eventId)
    }

    public func setPlan(_ plan: [PlanItem]) async throws {
        let lines: [JSONValue] = plan.map {
            .object(["product_id": .string($0.productId), "reason": .string($0.reason), "qty": .number(Decimal($0.qty))])
        }
        try await rest.rpc("set_plan", ["p_cart_id": .string(cartId), "p_plan": .array(lines)])
        await refreshCart()
    }

    public func dismissSuggestion() async throws {
        try await rest.rpc("dismiss_suggestion", ["p_cart_id": .string(cartId)])
        await refreshCart()
    }

    public func setStatus(_ status: TripStatus) async throws {
        guard status != .paid else { throw KartBackendError.invalidStatus }
        try await rest.rpc("set_cart_status", ["p_cart_id": .string(cartId), "p_status": .string(status.rawValue)])
        await refreshCart()
    }

    public func checkout(provider: String) async throws -> Receipt {
        do {
            let receipt: Receipt = try await rest.rpc("checkout", ["p_cart_id": .string(cartId), "p_provider": .string(provider)])
            self.receipt = receipt
            await refreshCart()
            return receipt
        } catch let error as PostgRESTError {
            if let count = error.unresolvedCount { throw KartBackendError.unresolvedItems(count: count) }
            throw error
        }
    }

    public func endTrip() async throws {
        try await setStatus(.idle)
    }

    public func appendTranscript(_ role: TranscriptLine.Role, _ text: String) async throws {
        try await rest.rpc("append_transcript", ["p_cart_id": .string(cartId), "p_role": .string(role.rawValue), "p_text": .string(text)])
        await refreshTranscript()
    }

    // MARK: Debug levers (the Pi's call)

    public func simulateVision(_ type: CartEventType, productId: String?, confidence: Double, label: String) async {
        try? await applyEvent(type, productId: productId, source: "vision", method: "local", confidence: confidence, label: label,
                              resolving: nil)
    }

    private func applyEvent(_ type: CartEventType, productId: String?, source: String, method: String, confidence: Double,
                            label: String?, resolving eventId: UUID?) async throws {
        try await rest.rpc("apply_cart_event", [
            "p_cart_id": .string(cartId),
            "p_type": .string(type.rawValue),
            "p_product_id": .optional(productId),
            "p_confidence": .number(Decimal(confidence)),
            "p_source": .string(source),
            "p_label": .optional(label),
            "p_camera": .null,
            "p_snapshot_url": .null,
            "p_event_id": .string(UUID().uuidString.lowercased()),
            "p_method": .string(method),
            "p_resolves_event_id": .optional(eventId?.uuidString.lowercased()),
        ])
        await refreshCart()
        await refreshEvents()
    }

    // MARK: Refetching

    private func schedule(_ slice: Slice) {
        pending[slice]?.cancel()
        pending[slice] = Task { [weak self] in
            try? await Task.sleep(for: .milliseconds(150))
            guard !Task.isCancelled, let self else { return }
            switch slice {
            case .cart: await self.refreshCart()
            case .events: await self.refreshEvents()
            case .transcript: await self.refreshTranscript()
            case .receipt: await self.refreshReceipt()
            case .catalog: await self.refreshCatalog()
            }
        }
    }

    private func fetch<T: Decodable & Sendable>(_ path: String, as type: T.Type) async -> [T]? {
        do {
            let rows = try await rest.select(path, as: type)
            lastError = nil
            return rows
        } catch {
            let table = path.prefix { $0 != "?" }
            lastError = "\(table): \(error)"
            return nil
        }
    }

    private func refreshCart(force: Bool = false) async {
        guard let fresh = await fetch("carts?cart_id=eq.\(cartId)", as: CartState.self)?.first else { return }
        let tripChanged = fresh.tripId != cart.tripId
        cart = fresh
        if tripChanged || force {
            await refreshEvents()
            await refreshTranscript()
            await refreshReceipt()
        }
    }

    private func refreshEvents() async {
        guard let trip = cart.tripId?.uuidString.lowercased() else { events = []; return }
        if let rows = await fetch("cart_events?cart_id=eq.\(cartId)&trip_id=eq.\(trip)&order=id", as: CartEvent.self) {
            events = rows
        }
    }

    private func refreshTranscript() async {
        guard let trip = cart.tripId?.uuidString.lowercased() else { transcript = []; return }
        if let rows = await fetch("transcript?cart_id=eq.\(cartId)&trip_id=eq.\(trip)&order=id&select=id,role,text,created_at",
                                  as: TranscriptLine.self) {
            transcript = rows
        }
    }

    private func refreshReceipt() async {
        guard let trip = cart.tripId?.uuidString.lowercased() else { receipt = nil; return }
        if let rows = await fetch("receipts?cart_id=eq.\(cartId)&trip_id=eq.\(trip)&order=id.desc&limit=1", as: Receipt.self) {
            receipt = rows.first
        }
    }

    private func refreshCatalog() async {
        guard let products = await fetch("products?active=is.true&order=sort", as: Product.self),
              let deals = await fetch("deals?active=is.true&order=sort", as: Deal.self) else { return }
        catalog = Catalog(layout: catalog.layout, products: products, deals: deals)
    }
}
