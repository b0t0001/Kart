import Foundation

public enum CartChange: Sendable, Equatable {
    case added(productId: String)
    case removed(productId: String)
    case priceDropped(productId: String, from: Decimal, to: Decimal)
}

/// What changed between two snapshots of the same trip's cart (drives chimes, reactions, and Kart's lines).
public enum CartDiff {
    public static func changes(from old: CartState, to new: CartState) -> [CartChange] {
        guard old.tripId == new.tripId else { return [] }
        let before = Dictionary(old.items.map { ($0.productId, $0) }, uniquingKeysWith: { first, _ in first })
        let after = Dictionary(new.items.map { ($0.productId, $0) }, uniquingKeysWith: { first, _ in first })
        var changes: [CartChange] = []
        for item in new.items {
            guard let previous = before[item.productId] else {
                changes.append(.added(productId: item.productId))
                continue
            }
            if item.qty > previous.qty {
                changes.append(.added(productId: item.productId))
            } else if item.qty < previous.qty {
                changes.append(.removed(productId: item.productId))
            } else if item.price < previous.price {
                changes.append(.priceDropped(productId: item.productId, from: previous.price, to: item.price))
            }
        }
        for item in old.items where after[item.productId] == nil {
            changes.append(.removed(productId: item.productId))
        }
        return changes
    }
}
