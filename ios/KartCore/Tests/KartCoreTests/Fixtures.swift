import Foundation
import Testing
@testable import KartCore

enum Fixtures {
    /// ios/KartCore/Tests/KartCoreTests/Fixtures.swift → repo root → data/store.json
    static let storeURL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent()
        .appending(path: "data/store.json")

    static func catalog() throws -> Catalog { try Catalog.load(from: storeURL) }

    /// How many products the published file lists (read straight from the JSON, not through the decoder).
    static func productCount() throws -> Int {
        let raw = try JSONSerialization.jsonObject(with: Data(contentsOf: storeURL)) as? [String: Any]
        return (raw?["products"] as? [Any])?.count ?? 0
    }

    /// A deal card's line as the data says it today: "Garlic Bread is $1 off in Aisle 8. Want it?".
    static func dealLine(_ dealId: String) throws -> String {
        let catalog = try catalog()
        let deal = try #require(catalog.deals.first { $0.id == dealId })
        let product = try #require(catalog.product(deal.productId))
        let aisle = catalog.section(product.section)?.aisleLabel ?? product.section
        return "\(product.shortName) is \(deal.label) in \(aisle). Want it?"
    }
}

extension Fixtures {
    /// `member_profile('1029')` as the backend returns it (CONTRACT v0.14; backend/members.py show).
    static let memberProfileJSON = """
    {"member": {"member_id": "1029", "name": "Dylan", "household": 4, "since": "2026-08-14", "trips": 15},
     "today": "2026-10-24", "weekday": "Saturday",
     "picks": [{"kind": "event", "aisle": "Aisle 6", "reason": "Leo's soccer party · tomorrow", "memory_id": 16,
                "product_id": "barilla-spaghetti", "short_name": "Spaghetti"},
               {"kind": "due", "aisle": "Aisle 2", "reason": "every week · last Sat", "product_id": "whole-milk",
                "short_name": "Milk"}],
     "usuals": [{"last": "2026-10-17", "times": 10, "weekday": "Saturday", "every_days": 7, "product_id": "whole-milk",
                 "short_name": "Milk"}],
     "memories": [{"id": 16, "kind": "event", "text": "Leo's soccer party, pasta for the team", "event_date": "2026-10-25",
                   "days_until": 1, "upcoming": true,
                   "items": [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 1}]},
                  {"id": 17, "kind": "preference", "text": "Likes the Marinara here", "event_date": null,
                   "days_until": null, "upcoming": false, "items": null}],
     "last_trip": {"date": "2026-10-17", "items": ["Milk", "Tortillas"], "total": 51.2}}
    """
}
