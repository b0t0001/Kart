import Foundation

public enum Screen: Sendable, Equatable {
    case welcome, greeting, shopping, checkout, receipt
}

public enum TripRouter {
    /// Greeting lasts until the shopper first speaks or the trip has content.
    public static func screen(cart: CartState, transcript: [TranscriptLine]) -> Screen {
        switch cart.status {
        case .idle: return .welcome
        case .checkout: return .checkout
        case .paid: return .receipt
        case .shopping:
            let quiet = !transcript.contains { $0.role == .user } && cart.items.isEmpty && cart.plan.isEmpty
            return quiet ? .greeting : .shopping
        }
    }
}
