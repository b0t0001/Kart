import Foundation

public struct ProductMatch: Sendable, Equatable {
    public let product: Product
    public let score: Double

    public init(product: Product, score: Double) {
        self.product = product
        self.score = score
    }
}

/// Turns a vision label ("red jar of Rao's marinara") into catalog guesses for a confirm card.
public enum LabelMatcher {
    private static let stopwords: Set<String> = ["the", "a", "an", "of", "and", "with", "in", "for", "jar", "box", "bag", "pack"]
    private static let units: Set<String> = ["oz", "lb", "ct"]

    public static func matches(for label: String, in products: [Product], limit: Int = 3) -> [ProductMatch] {
        let labelTokens = tokens(label)
        guard !labelTokens.isEmpty else { return [] }
        let scored = products.enumerated().compactMap { index, product -> (Int, ProductMatch)? in
            let productTokens = tokens(([product.name, product.shortName, product.category] + product.tags).joined(separator: " "))
            let hits = labelTokens.filter(productTokens.contains).count
            guard hits > 0 else { return nil }
            return (index, ProductMatch(product: product, score: Double(hits) / Double(labelTokens.count)))
        }
        return scored
            .sorted { $0.1.score != $1.1.score ? $0.1.score > $1.1.score : $0.0 < $1.0 }
            .prefix(limit)
            .map(\.1)
    }

    static func tokens(_ text: String) -> [String] {
        let cleaned = text.lowercased().replacingOccurrences(of: "'", with: "").replacingOccurrences(of: "’", with: "")
        return cleaned
            .split { !$0.isLetter && !$0.isNumber }
            .map(String.init)
            .filter { !stopwords.contains($0) && !units.contains($0) && !$0.allSatisfy(\.isNumber) }
    }
}
