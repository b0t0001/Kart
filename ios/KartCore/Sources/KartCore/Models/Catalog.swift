import Foundation

/// The shape of `data/store.json` (contract §2).
public struct StoreFile: Decodable, Sendable, Equatable {
    public var version: Int
    public var store: StoreInfo
    public var entrance: GridPoint
    public var sections: [Section]
    public var products: [Product]
    public var deals: [Deal]
}

public struct StoreInfo: Codable, Sendable, Equatable {
    public var name: String
    public var width: Int
    public var height: Int

    public init(name: String, width: Int, height: Int) {
        self.name = name
        self.width = width
        self.height = height
    }
}

public struct GridPoint: Codable, Sendable, Equatable {
    public var x: Int
    public var y: Int

    public init(x: Int, y: Int) {
        self.x = x
        self.y = y
    }
}

public struct Section: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var name: String
    public var x: Int
    public var y: Int
    public var w: Int
    public var h: Int

    public init(id: String, name: String, x: Int, y: Int, w: Int, h: Int) {
        self.id = id
        self.name = name
        self.x = x
        self.y = y
        self.w = w
        self.h = h
    }

    /// "Aisle 6" from "Aisle 6 · Pasta & Sauce"; the whole name when there's no separator.
    public var aisleLabel: String { nameParts.label }
    /// "Pasta & Sauce" from "Aisle 6 · Pasta & Sauce"; empty when there's no separator.
    public var title: String { nameParts.title }

    private var nameParts: (label: String, title: String) {
        guard let range = name.range(of: " · ") else { return (name, "") }
        return (String(name[..<range.lowerBound]), String(name[range.upperBound...]))
    }
}

public struct Product: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var name: String
    public var shortName: String
    public var price: Decimal
    public var section: String
    public var category: String
    public var tags: [String]
    public var stock: Int

    public init(id: String, name: String, shortName: String, price: Decimal, section: String,
                category: String, tags: [String], stock: Int) {
        self.id = id
        self.name = name
        self.shortName = shortName
        self.price = price
        self.section = section
        self.category = category
        self.tags = tags
        self.stock = stock
    }
}

public enum DealType: String, Codable, Sendable, Equatable {
    case amountOff = "amount_off"
    case percentOff = "percent_off"
}

public struct Deal: Codable, Sendable, Equatable, Identifiable {
    public var id: String
    public var productId: String
    public var type: DealType
    public var value: Decimal
    public var label: String
    public var pairsWith: [String]
    public var endsAt: Date?

    public init(id: String, productId: String, type: DealType, value: Decimal, label: String,
                pairsWith: [String], endsAt: Date? = nil) {
        self.id = id
        self.productId = productId
        self.type = type
        self.value = value
        self.label = label
        self.pairsWith = pairsWith
        self.endsAt = endsAt
    }
}

public struct StoreLayout: Sendable, Equatable {
    public var store: StoreInfo
    public var entrance: GridPoint
    public var sections: [Section]

    public init(store: StoreInfo, entrance: GridPoint, sections: [Section]) {
        self.store = store
        self.entrance = entrance
        self.sections = sections
    }
}

/// Store layout plus the products and deals the app knows about.
public struct Catalog: Sendable, Equatable {
    public var layout: StoreLayout
    public var products: [Product]
    public var deals: [Deal]

    public init(layout: StoreLayout, products: [Product], deals: [Deal]) {
        self.layout = layout
        self.products = products
        self.deals = deals
    }

    public func product(_ id: String) -> Product? { products.first { $0.id == id } }

    public func section(_ id: String) -> Section? { layout.sections.first { $0.id == id } }

    /// The first deal for the product that hasn't ended by `now`.
    public func activeDeal(for productId: String, at now: Date) -> Deal? {
        deals.first { $0.productId == productId && ($0.endsAt.map { $0 > now } ?? true) }
    }

    public static func load(from url: URL) throws -> Catalog {
        let file = try KartJSON.decoder().decode(StoreFile.self, from: Data(contentsOf: url))
        return Catalog(layout: StoreLayout(store: file.store, entrance: file.entrance, sections: file.sections),
                       products: file.products, deals: file.deals)
    }
}
