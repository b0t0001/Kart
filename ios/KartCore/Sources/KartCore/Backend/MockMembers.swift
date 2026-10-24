import Foundation

/// A day in the store's time zone (America/Los_Angeles), as days since 1970-01-01. The backend's member
/// memory dates everything this way, never in UTC.
enum StoreDay {
    static let zone = TimeZone(identifier: "America/Los_Angeles")!

    static func day(_ date: Date) -> Int {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = zone
        var utc = Calendar(identifier: .gregorian)
        utc.timeZone = TimeZone(identifier: "UTC")!
        let midnight = utc.date(from: local.dateComponents([.year, .month, .day], from: date))!
        return Int((midnight.timeIntervalSince1970 / 86_400).rounded(.down))
    }

    static func day(iso: String) -> Int? {
        let f = formatter("yyyy-MM-dd")
        return f.date(from: iso).map { Int(($0.timeIntervalSince1970 / 86_400).rounded(.down)) }
    }

    static func iso(_ day: Int) -> String { format(day, "yyyy-MM-dd") }

    /// "Sat" (`EEE`), "Saturday" (`EEEE`), "Oct 31" (`MMM d`).
    static func format(_ day: Int, _ pattern: String) -> String {
        formatter(pattern).string(from: Date(timeIntervalSince1970: Double(day) * 86_400 + 43_200))
    }

    private static func formatter(_ pattern: String) -> DateFormatter {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "UTC")
        f.dateFormat = pattern
        return f
    }
}

/// The mock's memory of one member (contract v0.14, beta): `member_profile`'s rules in miniature, so the
/// offline demo rehearses the member beat. Dylan (1029) comes with a small history; any other number is new.
struct MockMemberStore {
    struct Purchase {
        var productId: String
        var day: Int
        var qty: Int
        var price: Decimal
    }

    struct Memory {
        var id: Int
        var kind: String
        var text: String
        var eventDay: Int?
        var items: [SavedItem]?
        var createdDay: Int
    }

    /// Never remembered (spec §3.9).
    static let sensitive: Set<String> = ["pharmacy", "health", "medicine", "personal-care", "baby", "pregnancy", "adult"]

    var name: String?
    var household: Int?
    var since: Int
    var purchases: [Purchase] = []
    var memories: [Memory] = []

    static func empty(today: Int) -> MockMemberStore { MockMemberStore(since: today) }

    /// Milk every week and tortillas most weeks on today's weekday. No party: in the demo it's told live (Act 1).
    static func dylan(today: Int, catalog: Catalog) -> MockMemberStore {
        var store = MockMemberStore(name: "Dylan", household: 4, since: today - 71)
        func buy(_ id: String, _ daysAgo: [Int]) {
            guard let product = catalog.product(id) else { return }
            store.purchases += daysAgo.map { Purchase(productId: id, day: today - $0, qty: 1, price: product.price) }
        }
        buy("whole-milk", [7, 14, 21, 28])
        buy("mission-tortillas", [3, 7, 14, 21])
        buy("tostitos-chips", [7, 14, 21, 28])
        if let marinara = catalog.product("rao-marinara") {
            store.memories.append(Memory(id: 17, kind: "preference", text: "Likes the \(marinara.shortName) here",
                                         createdDay: today - 21))
        }
        return store
    }

    func profile(memberId: String, today: Int, taken: Set<String>, catalog: Catalog, liveDeals: Set<String>) -> MemberProfile {
        let bought = purchases.filter { $0.day <= today && !Self.sensitive.contains(catalog.product($0.productId)?.category ?? "") }
        var days: [String: [Int]] = [:]
        for p in bought { days[p.productId, default: []].append(p.day) }
        for (id, list) in days { days[id] = Array(Set(list)).sorted() }
        let trips = Set(bought.map(\.day))
        let weekday = { (day: Int) in ((day % 7) + 11) % 7 }          // 0 = Sunday (1970-01-01 was a Thursday)

        func every(_ list: [Int]) -> Int? {
            let gaps = zip(list.dropFirst(), list).map { $0 - $1 }.sorted()
            guard !gaps.isEmpty else { return nil }
            let mid = gaps.count / 2
            let median = gaps.count % 2 == 1 ? Double(gaps[mid]) : Double(gaps[mid - 1] + gaps[mid]) / 2
            return Int(median.rounded())
        }
        func ok(_ id: String) -> Bool {
            guard let p = catalog.product(id) else { return false }
            return p.stock > 0 && !liveDeals.contains(id) && !taken.contains(id)
        }

        typealias Candidate = (kind: MemberPick.Kind, productId: String, reason: String, memoryId: Int?)
        var candidates: [Candidate] = []
        let soon = memories.filter { m in
            guard m.items?.isEmpty == false, let day = m.eventDay else { return false }
            return m.kind == "event" ? (today...today + 14).contains(day) : m.kind == "reminder" && (-3...1).contains(day - today)
        }.sorted { ($0.eventDay ?? .max, $0.id) < ($1.eventDay ?? .max, $1.id) }
        for m in soon {
            let when = m.kind == "reminder" ? "reminder" : Self.when(m.eventDay!, today)
            for item in m.items ?? [] { candidates.append((.event, item.productId, "\(Self.label(m.text)) · \(when)", m.id)) }
        }
        let due = days.compactMap { id, list -> (String, Double, Int, Int)? in
            guard list.count >= 3, let e = every(list), e > 0, Double(today - list.last!) >= 0.85 * Double(e) else { return nil }
            return (id, Double(today - list.last!) / Double(e), list.count, e)
        }.sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.2 != $1.2 ? $0.2 > $1.2 : $0.0 < $1.0 }
        for (id, _, _, e) in due {
            let last = days[id]!.last!
            let when = today - last <= 7 ? StoreDay.format(last, "EEE") : StoreDay.format(last, "MMM d")
            candidates.append((.due, id, "\(Self.every(e)) · last \(when)", nil))
        }
        let weekdayTrips = trips.filter { weekday($0) == weekday(today) }.count
        if weekdayTrips >= 2 {
            let usual = days.compactMap { id, list -> (String, Double, Int)? in
                let share = Double(list.filter { weekday($0) == weekday(today) }.count) / Double(weekdayTrips)
                return share >= 0.6 ? (id, share, list.count) : nil
            }.sorted { $0.1 != $1.1 ? $0.1 > $1.1 : $0.2 != $1.2 ? $0.2 > $1.2 : $0.0 < $1.0 }
            for (id, _, _) in usual { candidates.append((.usual, id, "your \(StoreDay.format(today, "EEEE")) usual", nil)) }
        }

        var chosen: [Candidate] = []
        for kind in [MemberPick.Kind.event, .due, .usual] {
            if chosen.count < 3, let c = candidates.first(where: { $0.kind == kind && ok($0.productId) && !chosen.map(\.productId).contains($0.productId) }) {
                chosen.append(c)
            }
        }
        for c in candidates where chosen.count < 3 && c.kind != .event        // a saved list is one line on the card
            && ok(c.productId) && !chosen.map(\.productId).contains(c.productId) {
            chosen.append(c)
        }
        let picks = chosen.map { c in
            MemberPick(productId: c.productId, shortName: catalog.product(c.productId)?.shortName ?? c.productId, kind: c.kind,
                       reason: c.reason, aisle: catalog.product(c.productId).flatMap { catalog.section($0.section)?.aisleLabel },
                       memoryId: c.memoryId)
        }

        let usuals = days.filter { $0.value.count >= 2 }
            .sorted { $0.value.count != $1.value.count ? $0.value.count > $1.value.count : $0.value.last! > $1.value.last! }
            .prefix(6)
            .map { id, list -> MemberUsual in
                let byDay = Dictionary(grouping: list, by: weekday)
                let top = byDay.max { $0.value.count < $1.value.count }!
                let usualDay = Double(top.value.count) / Double(list.count) >= 0.6 ? StoreDay.format(top.value[0], "EEEE") : nil
                return MemberUsual(productId: id, shortName: catalog.product(id)?.shortName ?? id, times: list.count,
                                   everyDays: every(list), last: StoreDay.iso(list.last!), weekday: usualDay)
            }

        func upcoming(_ m: Memory) -> Bool {
            switch m.kind {
            case "event": return m.eventDay.map { $0 >= today } ?? (m.createdDay >= today - 30)
            case "reminder": return m.eventDay.map { $0 >= today - 3 } ?? false
            default: return false
            }
        }
        let first = { (m: Memory) in upcoming(m) || (m.eventDay.map { $0 - today >= -7 } ?? false) }
        let ordered = memories.sorted { a, b in
            if first(a) != first(b) { return first(a) }
            if first(a), a.eventDay != b.eventDay { return (a.eventDay ?? .max) < (b.eventDay ?? .max) }
            return a.createdDay != b.createdDay ? a.createdDay > b.createdDay : a.id > b.id
        }
        let memoryRows = ordered.map { m in
            MemberMemory(id: m.id, kind: m.kind, text: m.text, eventDate: m.eventDay.map(StoreDay.iso),
                         daysUntil: m.eventDay.map { $0 - today }, upcoming: upcoming(m), items: m.items)
        }

        var lastTrip: LastTrip?
        if let last = trips.max() {
            let lines = bought.filter { $0.day == last }
            lastTrip = LastTrip(date: StoreDay.iso(last),
                                items: Array(Set(lines.map { catalog.product($0.productId)?.shortName ?? $0.productId })).sorted(),
                                total: lines.reduce(0) { $0 + $1.price * Decimal($1.qty) })
        }
        return MemberProfile(member: MemberInfo(memberId: memberId, name: name, household: household,
                                                since: StoreDay.iso(since), trips: trips.count),
                             today: StoreDay.iso(today), weekday: StoreDay.format(today, "EEEE"), picks: picks,
                             usuals: Array(usuals), memories: memoryRows, lastTrip: lastTrip)
    }

    static func label(_ text: String) -> String {
        String(text.split(separator: ",", maxSplits: 1).first.map { $0.trimmingCharacters(in: .whitespaces) } ?? text).prefix(28).description
    }

    static func when(_ day: Int, _ today: Int) -> String {
        switch day - today {
        case 0: "today"
        case 1: "tomorrow"
        case 2...6: StoreDay.format(day, "EEE")
        default: StoreDay.format(day, "MMM d")
        }
    }

    static func every(_ days: Int) -> String {
        switch days {
        case 6...8: "every week"
        case 13...15: "every 2 weeks"
        case 27...31: "every month"
        default: "every \(days) days"
        }
    }
}
