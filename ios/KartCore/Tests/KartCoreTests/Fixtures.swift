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
