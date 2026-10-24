import Foundation

public struct PaymentResult: Sendable, Equatable {
    public let approved: Bool
    public let reference: String

    public init(approved: Bool, reference: String) {
        self.approved = approved
        self.reference = reference
    }
}

public enum PaymentError: Error, Equatable {
    case declined
}

/// The tap-to-pay step. Simulated in v1; a Visa-supported plugin can replace it.
@MainActor public protocol PaymentProvider: AnyObject {
    var name: String { get }
    func pay(amount: Decimal, tripId: UUID) async throws -> PaymentResult
}

@MainActor public final class SimulatedPaymentProvider: PaymentProvider {
    public let name = "simulated"
    /// Debug panel: make the next payments fail.
    public var forceFailure = false
    private let delay: Duration

    public init(delay: Duration = .milliseconds(1200)) {
        self.delay = delay
    }

    public func pay(amount: Decimal, tripId: UUID) async throws -> PaymentResult {
        try? await Task.sleep(for: delay)
        if forceFailure { throw PaymentError.declined }
        return PaymentResult(approved: true, reference: "SIM-\(tripId.uuidString.prefix(8))")
    }
}
