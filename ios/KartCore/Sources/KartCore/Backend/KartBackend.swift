import Foundation
import Observation

public enum ConnectionState: Sendable, Equatable {
    case online, reconnecting
}

public enum KartBackendError: Error, Equatable {
    case unresolvedItems(count: Int)
    case unknownProduct(String)
    case invalidStatus
    case noActiveTrip
}

/// Everything the iPad reads from and writes to the backend (contract §3, §5a).
/// `MockKartBackend` imitates the real rules; the Supabase implementation arrives in milestone 2.
@MainActor public protocol KartBackend: AnyObject, Observable {
    var cart: CartState { get }
    /// This trip's events, oldest first.
    var events: [CartEvent] { get }
    var catalog: Catalog { get }
    /// This trip's transcript, oldest first.
    var transcript: [TranscriptLine] { get }
    var connection: ConnectionState { get }
    /// This trip's receipt once `checkout` has run (the `receipts` row).
    var receipt: Receipt? { get }

    /// `reset_cart`: a new trip.
    func startTrip() async throws
    func applyManualEvent(_ type: CartEventType, productId: String, resolving eventId: UUID?) async throws
    /// "Remove" on a confirm card: `apply_cart_event(removed, null, manual, p_resolves_event_id)`.
    func resolveUnknown(eventId: UUID) async throws
    /// The backend fills and reorders the plan.
    func setPlan(_ plan: [PlanItem]) async throws
    /// P5.
    func dismissSuggestion() async throws
    /// v0.12 beta: answer the quantity nudge ("Keep it" / "Got it").
    func dismissNudge(_ action: NudgeAction) async throws
    /// v0.12: a per-cart feature switch, e.g. `quantity_nudges`.
    func setFeature(_ feature: String, on: Bool) async throws
    /// P2: idle, shopping, or checkout; `.paid` throws `.invalidStatus`.
    func setStatus(_ status: TripStatus) async throws
    /// P8: the receipts row, idempotent per trip.
    func checkout(provider: String) async throws -> Receipt
    /// Status back to idle.
    func endTrip() async throws
    /// P6, agent side.
    func appendTranscript(_ role: TranscriptLine.Role, _ text: String) async throws
}
