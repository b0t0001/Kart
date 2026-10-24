import Foundation
import Testing
@testable import KartCore

let tripA = UUID()
let tripB = UUID()

/// A `.shopping` cart built from (productId, price, qty) tuples.
func cart(_ lines: [(String, String, Int)], trip: UUID = tripA) -> CartState {
    var c = CartState.empty(cartId: "7")
    c.status = .shopping
    c.tripId = trip
    c.items = lines.map { CartItem(productId: $0.0, name: $0.0, price: Decimal(string: $0.1)!, qty: $0.2, addedAt: .now) }
    c.itemCount = lines.reduce(0) { $0 + $1.2 }
    return c
}

func line(_ role: TranscriptLine.Role, _ text: String) -> TranscriptLine {
    TranscriptLine(id: 0, role: role, text: text, createdAt: .now)
}
