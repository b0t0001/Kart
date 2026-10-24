import Foundation
@testable import KartCore

enum Fixtures {
    /// ios/KartCore/Tests/KartCoreTests/Fixtures.swift → repo root → data/store.json
    static let storeURL = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent()
        .appending(path: "data/store.json")

    static func catalog() throws -> Catalog { try Catalog.load(from: storeURL) }
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
