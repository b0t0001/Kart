import Foundation

/// The next aisle to visit, drawn on the Next stop card and the map.
public struct NextStop: Sendable, Equatable {
    public let sectionId: String
    public let aisleLabel: String
    public let shortName: String
    public let text: String

    public init(sectionId: String, aisleLabel: String, shortName: String, text: String) {
        self.sectionId = sectionId
        self.aisleLabel = aisleLabel
        self.shortName = shortName
        self.text = text
    }

    /// The first not-done, in-stock plan line the catalog knows. The backend already ordered the plan by route.
    public static func from(cart: CartState, catalog: Catalog) -> NextStop? {
        for line in cart.plan where !line.done && line.inStock != false {
            guard let product = catalog.product(line.productId) else { continue }
            let aisle = line.aisle ?? catalog.section(product.section)?.aisleLabel ?? product.section
            return NextStop(sectionId: product.section, aisleLabel: aisle, shortName: product.shortName,
                            text: cart.nextStep ?? "\(aisle) → \(product.shortName)")
        }
        return nil
    }

    public static func hereText(cart: CartState, catalog: Catalog) -> String {
        guard let location = cart.location, let section = catalog.section(location.section) else {
            return "Starting at the entrance"
        }
        return section.title.isEmpty ? "You're in \(section.aisleLabel)" : "You're in \(section.aisleLabel) · \(section.title)"
    }
}
