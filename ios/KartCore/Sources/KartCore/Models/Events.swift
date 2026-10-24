import Foundation

public enum CartEventType: String, Codable, Sendable, Equatable {
    case added, removed
}

public enum CartEventSource: String, Codable, Sendable, Equatable {
    case vision, manual
}

/// One `cart_events` row: the audit trail behind "what the AI saw".
public struct CartEvent: Codable, Sendable, Equatable, Identifiable {
    public var id: Int64
    public var eventId: UUID
    public var cartId: String
    public var tripId: UUID?
    public var type: CartEventType
    public var productId: String?
    public var confidence: Double
    public var source: CartEventSource
    public var label: String?
    public var snapshotUrl: URL?
    public var applied: Bool?
    public var createdAt: Date
    public var resolvedAt: Date?

    public init(id: Int64, eventId: UUID, cartId: String, tripId: UUID? = nil, type: CartEventType,
                productId: String? = nil, confidence: Double, source: CartEventSource, label: String? = nil,
                snapshotUrl: URL? = nil, applied: Bool? = nil, createdAt: Date, resolvedAt: Date? = nil) {
        self.id = id
        self.eventId = eventId
        self.cartId = cartId
        self.tripId = tripId
        self.type = type
        self.productId = productId
        self.confidence = confidence
        self.source = source
        self.label = label
        self.snapshotUrl = snapshotUrl
        self.applied = applied
        self.createdAt = createdAt
        self.resolvedAt = resolvedAt
    }

    /// An unrecognized vision add the shopper still has to confirm.
    public var needsConfirmation: Bool {
        guard source == .vision, type == .added, resolvedAt == nil else { return false }
        if let applied { return !applied }
        return productId == nil
    }
}

/// One `transcript` row (P6): live captions.
public struct TranscriptLine: Codable, Sendable, Equatable, Identifiable {
    public enum Role: String, Codable, Sendable, Equatable {
        case user, agent
    }

    public var id: Int64
    public var role: Role
    public var text: String
    public var createdAt: Date

    public init(id: Int64, role: Role, text: String, createdAt: Date) {
        self.id = id
        self.role = role
        self.text = text
        self.createdAt = createdAt
    }
}

/// One `receipts` row (P8), returned by `checkout`.
public struct Receipt: Codable, Sendable, Equatable {
    public var id: Int64?
    public var cartId: String
    public var tripId: UUID?
    public var total: Decimal
    public var savings: Decimal
    public var itemCount: Int
    public var durationS: Int
    public var provider: String
    public var status: String
    public var items: [CartItem]
    public var createdAt: Date?

    public init(id: Int64? = nil, cartId: String, tripId: UUID? = nil, total: Decimal, savings: Decimal,
                itemCount: Int, durationS: Int, provider: String, status: String, items: [CartItem],
                createdAt: Date? = nil) {
        self.id = id
        self.cartId = cartId
        self.tripId = tripId
        self.total = total
        self.savings = savings
        self.itemCount = itemCount
        self.durationS = durationS
        self.provider = provider
        self.status = status
        self.items = items
        self.createdAt = createdAt
    }

    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try c.decodeIfPresent(Int64.self, forKey: .id),
                  cartId: try c.decode(String.self, forKey: .cartId),
                  tripId: try c.decodeIfPresent(UUID.self, forKey: .tripId),
                  total: try c.decode(Decimal.self, forKey: .total),
                  savings: try c.decodeIfPresent(Decimal.self, forKey: .savings) ?? 0,
                  itemCount: try c.decodeIfPresent(Int.self, forKey: .itemCount) ?? 0,
                  durationS: try c.decodeIfPresent(Int.self, forKey: .durationS) ?? 0,
                  provider: try c.decodeIfPresent(String.self, forKey: .provider) ?? "simulated",
                  status: try c.decodeIfPresent(String.self, forKey: .status) ?? "paid",
                  items: try c.decodeIfPresent([CartItem].self, forKey: .items) ?? [],
                  createdAt: try c.decodeIfPresent(Date.self, forKey: .createdAt))
    }
}
