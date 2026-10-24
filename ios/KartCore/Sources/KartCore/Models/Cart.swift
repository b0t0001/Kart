import Foundation

/// `carts.status` (P2).
public enum TripStatus: String, Codable, Sendable, Equatable {
    case idle, shopping, checkout, paid
}

/// One line of `carts.items`: one line per product (contract §3a).
public struct CartItem: Codable, Sendable, Equatable, Identifiable {
    public var productId: String
    public var name: String
    public var shortName: String?
    public var price: Decimal
    public var listPrice: Decimal?
    public var qty: Int
    public var dealLabel: String?
    public var dealId: String?
    public var section: String?
    public var addedAt: Date
    public var lastAddedAt: Date?

    public var id: String { productId }

    public init(productId: String, name: String, shortName: String? = nil, price: Decimal, listPrice: Decimal? = nil,
                qty: Int, dealLabel: String? = nil, dealId: String? = nil, section: String? = nil,
                addedAt: Date, lastAddedAt: Date? = nil) {
        self.productId = productId
        self.name = name
        self.shortName = shortName
        self.price = price
        self.listPrice = listPrice
        self.qty = qty
        self.dealLabel = dealLabel
        self.dealId = dealId
        self.section = section
        self.addedAt = addedAt
        self.lastAddedAt = lastAddedAt
    }
}

/// One line of `carts.plan`. The agent sends `productId`, `reason` and `qty`; the backend fills the rest
/// and orders the plan by walking route.
public struct PlanItem: Codable, Sendable, Equatable, Identifiable {
    public var productId: String
    public var reason: String
    public var qty: Int
    public var done: Bool
    public var name: String?
    public var section: String?
    public var aisle: String?
    public var inStock: Bool?
    public var dealLabel: String?
    /// The agent's math for the amount, e.g. "8 people × 2 tacos ≈ 16 tortillas → 2 packs of 10" (v0.12).
    public var basis: String?

    public var id: String { productId }

    public init(productId: String, reason: String, qty: Int, done: Bool, name: String? = nil, section: String? = nil,
                aisle: String? = nil, inStock: Bool? = nil, dealLabel: String? = nil, basis: String? = nil) {
        self.productId = productId
        self.reason = reason
        self.qty = qty
        self.done = done
        self.name = name
        self.section = section
        self.aisle = aisle
        self.inStock = inStock
        self.dealLabel = dealLabel
        self.basis = basis
    }

    /// What the agent sends with `set_plan`.
    public init(productId: String, reason: String, qty: Int = 1) {
        self.init(productId: productId, reason: reason, qty: qty, done: false)
    }

    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        self.init(productId: try c.decode(String.self, forKey: .productId),
                  reason: try c.decodeIfPresent(String.self, forKey: .reason) ?? "",
                  qty: try c.decodeIfPresent(Int.self, forKey: .qty) ?? 1,
                  done: try c.decodeIfPresent(Bool.self, forKey: .done) ?? false,
                  name: try c.decodeIfPresent(String.self, forKey: .name),
                  section: try c.decodeIfPresent(String.self, forKey: .section),
                  aisle: try c.decodeIfPresent(String.self, forKey: .aisle),
                  inStock: try c.decodeIfPresent(Bool.self, forKey: .inStock),
                  dealLabel: try c.decodeIfPresent(String.self, forKey: .dealLabel),
                  basis: try c.decodeIfPresent(String.self, forKey: .basis))
    }
}

/// `carts.nudge` (v0.12, beta): the cart's amount of a planned item doesn't match the list.
public enum NudgeKind: String, Codable, Sendable { case under, over }

/// `dismiss_nudge`: `keep` raises the list to what's in the cart; `ok` / `skip` acknowledge; `shop` ("go get them",
/// at checkout) also puts the cart back to shopping.
public enum NudgeAction: String, Sendable { case keep, ok, skip, shop }

/// One short item of the combined checkout nudge.
public struct NudgeItem: Codable, Sendable, Equatable {
    public var productId: String
    public var name: String?
    public var have: Int
    public var need: Int
    public var aisle: String?

    public init(productId: String, name: String? = nil, have: Int, need: Int, aisle: String? = nil) {
        self.productId = productId
        self.name = name
        self.have = have
        self.need = need
        self.aisle = aisle
    }
}

public struct Nudge: Codable, Sendable, Equatable {
    public var productId: String
    public var name: String?
    public var kind: NudgeKind
    public var have: Int
    public var need: Int
    public var basis: String?
    public var text: String
    public var savings: Decimal?
    public var aisle: String?
    public var at: Date?
    /// At checkout, every short item in walking order, answered once; the first one fills productId/have/need.
    public var items: [NudgeItem]?

    public init(productId: String, name: String? = nil, kind: NudgeKind, have: Int, need: Int, basis: String? = nil,
                text: String, savings: Decimal? = nil, aisle: String? = nil, at: Date? = nil, items: [NudgeItem]? = nil) {
        self.productId = productId
        self.name = name
        self.kind = kind
        self.have = have
        self.need = need
        self.basis = basis
        self.text = text
        self.savings = savings
        self.aisle = aisle
        self.at = at
        self.items = items
    }

    /// `carts.nudged` entry: once per product per direction per trip.
    public var key: String { "\(kind.rawValue):\(productId)" }        // as the backend writes it
}

/// `carts.suggestion`: the deal offered at the moment of decision. `text` is a complete spoken line.
public struct Suggestion: Codable, Sendable, Equatable {
    public var productId: String
    public var dealId: String
    public var text: String
    public var name: String?
    public var dealLabel: String?
    public var aisle: String?
    public var section: String?
    public var price: Decimal?
    public var salePrice: Decimal?
    public var offeredAt: Date?

    public init(productId: String, dealId: String, text: String, name: String? = nil, dealLabel: String? = nil,
                aisle: String? = nil, section: String? = nil, price: Decimal? = nil, salePrice: Decimal? = nil,
                offeredAt: Date? = nil) {
        self.productId = productId
        self.dealId = dealId
        self.text = text
        self.name = name
        self.dealLabel = dealLabel
        self.aisle = aisle
        self.section = section
        self.price = price
        self.salePrice = salePrice
        self.offeredAt = offeredAt
    }
}

/// `carts.location` (P3).
public struct CartLocation: Codable, Sendable, Equatable {
    public var section: String
    public var source: String
    public var at: Date

    public init(section: String, source: String, at: Date) {
        self.section = section
        self.source = source
        self.at = at
    }
}

/// The `carts` row for one cart (contract §3, §3a).
public struct CartState: Codable, Sendable, Equatable {
    public var cartId: String
    public var tripId: UUID?
    public var items: [CartItem]
    public var itemCount: Int
    public var total: Decimal
    public var savings: Decimal?
    public var plan: [PlanItem]
    public var nextStep: String?
    public var suggestion: Suggestion?
    public var suggestedDeals: [String]
    public var status: TripStatus
    public var tripStartedAt: Date?
    public var location: CartLocation?
    public var updatedAt: Date?
    /// Per-cart feature switches (v0.12), e.g. `["quantity_nudges": true]`.
    public var features: [String: Bool]
    public var nudge: Nudge?
    public var nudged: [String]
    /// Member memory beta (v0.14): who's signed in this trip, a counter bumped on memory writes, and the demo
    /// fast-forward date (`YYYY-MM-DD`, nil = real today).
    public var memberId: String?
    public var memberRev: Int
    public var demoDate: String?

    /// The quantity-nudge beta is on for this cart: only then does the iPad show nudges and +/−.
    public var quantityNudgesOn: Bool { features["quantity_nudges"] == true }
    /// The member-memory beta is on for this cart: only then does the iPad show sign-in and memory.
    public var memberMemoryOn: Bool { features["member_memory"] == true }

    public init(cartId: String, tripId: UUID? = nil, items: [CartItem], itemCount: Int, total: Decimal,
                savings: Decimal? = nil, plan: [PlanItem], nextStep: String? = nil, suggestion: Suggestion? = nil,
                suggestedDeals: [String], status: TripStatus, tripStartedAt: Date? = nil,
                location: CartLocation? = nil, updatedAt: Date? = nil, features: [String: Bool] = [:],
                nudge: Nudge? = nil, nudged: [String] = [], memberId: String? = nil, memberRev: Int = 0,
                demoDate: String? = nil) {
        self.cartId = cartId
        self.tripId = tripId
        self.items = items
        self.itemCount = itemCount
        self.total = total
        self.savings = savings
        self.plan = plan
        self.nextStep = nextStep
        self.suggestion = suggestion
        self.suggestedDeals = suggestedDeals
        self.status = status
        self.tripStartedAt = tripStartedAt
        self.location = location
        self.updatedAt = updatedAt
        self.features = features
        self.nudge = nudge
        self.nudged = nudged
        self.memberId = memberId
        self.memberRev = memberRev
        self.demoDate = demoDate
    }

    public static func empty(cartId: String) -> CartState {
        CartState(cartId: cartId, items: [], itemCount: 0, total: 0, plan: [], suggestedDeals: [], status: .idle)
    }

    public init(from decoder: any Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let items = try c.decodeIfPresent([CartItem].self, forKey: .items) ?? []
        self.init(cartId: try c.decode(String.self, forKey: .cartId),
                  tripId: try c.decodeIfPresent(UUID.self, forKey: .tripId),
                  items: items,
                  itemCount: try c.decodeIfPresent(Int.self, forKey: .itemCount) ?? items.reduce(0) { $0 + $1.qty },
                  total: try c.decodeIfPresent(Decimal.self, forKey: .total) ?? 0,
                  savings: try c.decodeIfPresent(Decimal.self, forKey: .savings),
                  plan: try c.decodeIfPresent([PlanItem].self, forKey: .plan) ?? [],
                  nextStep: try c.decodeIfPresent(String.self, forKey: .nextStep),
                  suggestion: try c.decodeIfPresent(Suggestion.self, forKey: .suggestion),
                  suggestedDeals: try c.decodeIfPresent([String].self, forKey: .suggestedDeals) ?? [],
                  status: try c.decodeIfPresent(TripStatus.self, forKey: .status) ?? .idle,
                  tripStartedAt: try c.decodeIfPresent(Date.self, forKey: .tripStartedAt),
                  location: try c.decodeIfPresent(CartLocation.self, forKey: .location),
                  updatedAt: try c.decodeIfPresent(Date.self, forKey: .updatedAt),
                  features: (try? c.decodeIfPresent([String: Bool].self, forKey: .features)) ?? [:],
                  nudge: try c.decodeIfPresent(Nudge.self, forKey: .nudge),
                  nudged: try c.decodeIfPresent([String].self, forKey: .nudged) ?? [],
                  memberId: try c.decodeIfPresent(String.self, forKey: .memberId),
                  memberRev: try c.decodeIfPresent(Int.self, forKey: .memberRev) ?? 0,
                  demoDate: try c.decodeIfPresent(String.self, forKey: .demoDate))
    }
}
