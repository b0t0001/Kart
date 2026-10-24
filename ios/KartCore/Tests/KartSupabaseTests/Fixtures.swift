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
