import Foundation

/// `member_profile(member, cart)` (contract v0.14, beta): who a signed-in member is and what Kart remembers.
/// The backend computes everything here, the picks and their reasons included; the iPad only shows it.
/// Dates stay `YYYY-MM-DD` strings in the store's time zone.
public struct MemberProfile: Codable, Sendable, Equatable {
    public var member: MemberInfo
    public var today: String
    public var weekday: String
    public var picks: [MemberPick]
    public var usuals: [MemberUsual]
    public var memories: [MemberMemory]
    public var lastTrip: LastTrip?

    public init(member: MemberInfo, today: String, weekday: String, picks: [MemberPick] = [],
                usuals: [MemberUsual] = [], memories: [MemberMemory] = [], lastTrip: LastTrip? = nil) {
        self.member = member
        self.today = today
        self.weekday = weekday
        self.picks = picks
        self.usuals = usuals
        self.memories = memories
        self.lastTrip = lastTrip
    }
}

public struct MemberInfo: Codable, Sendable, Equatable {
    public var memberId: String
    public var name: String?
    public var household: Int?
    public var since: String
    public var trips: Int

    public init(memberId: String, name: String? = nil, household: Int? = nil, since: String, trips: Int) {
        self.memberId = memberId
        self.name = name
        self.household = household
        self.since = since
        self.trips = trips
    }
}

/// One "For you" line: something that fits this week, and why.
public struct MemberPick: Codable, Sendable, Equatable, Identifiable {
    public enum Kind: String, Codable, Sendable {
        case event, due, usual

        public init(from decoder: any Decoder) throws {
            self = Kind(rawValue: try decoder.singleValueContainer().decode(String.self)) ?? .usual
        }
    }

    public var productId: String
    public var shortName: String
    public var kind: Kind
    public var reason: String
    public var aisle: String?
    public var memoryId: Int?

    public var id: String { productId }

    public init(productId: String, shortName: String, kind: Kind, reason: String, aisle: String? = nil, memoryId: Int? = nil) {
        self.productId = productId
        self.shortName = shortName
        self.kind = kind
        self.reason = reason
        self.aisle = aisle
        self.memoryId = memoryId
    }
}

public struct MemberUsual: Codable, Sendable, Equatable {
    public var productId: String
    public var shortName: String
    public var times: Int
    public var everyDays: Int?
    public var last: String
    public var weekday: String?

    public init(productId: String, shortName: String, times: Int, everyDays: Int? = nil, last: String, weekday: String? = nil) {
        self.productId = productId
        self.shortName = shortName
        self.times = times
        self.everyDays = everyDays
        self.last = last
        self.weekday = weekday
    }
}

/// Something Kart learned in conversation: an event or reminder (with a date and maybe a saved list),
/// a preference, or a note.
public struct MemberMemory: Codable, Sendable, Equatable, Identifiable {
    public var id: Int
    public var kind: String
    public var text: String
    public var eventDate: String?
    public var daysUntil: Int?
    public var upcoming: Bool?
    public var items: [SavedItem]?

    public init(id: Int, kind: String, text: String, eventDate: String? = nil, daysUntil: Int? = nil,
                upcoming: Bool? = nil, items: [SavedItem]? = nil) {
        self.id = id
        self.kind = kind
        self.text = text
        self.eventDate = eventDate
        self.daysUntil = daysUntil
        self.upcoming = upcoming
        self.items = items
    }

    /// "Coming up" as the backend judges it (dated and not past, or undated and fresh).
    public var isUpcoming: Bool { upcoming ?? ((daysUntil ?? -1) >= 0) }
    public var isPast: Bool { (daysUntil ?? 0) < 0 }
    /// "Leo's soccer party" from "Leo's soccer party, pasta for the team".
    public var title: String {
        text.split(separator: ",", maxSplits: 1).first.map { $0.trimmingCharacters(in: .whitespaces) } ?? text
    }
}

public struct SavedItem: Codable, Sendable, Equatable {
    public var productId: String
    public var shortName: String
    public var qty: Int

    public init(productId: String, shortName: String, qty: Int = 1) {
        self.productId = productId
        self.shortName = shortName
        self.qty = qty
    }
}

public struct LastTrip: Codable, Sendable, Equatable {
    public var date: String
    public var items: [String]
    public var total: Decimal
}

/// `member_lookup(id)`: the sign-in card's confirm step.
public struct MemberLookup: Codable, Sendable, Equatable {
    public var exists: Bool
    public var name: String?

    public init(exists: Bool, name: String? = nil) {
        self.exists = exists
        self.name = name
    }
}
