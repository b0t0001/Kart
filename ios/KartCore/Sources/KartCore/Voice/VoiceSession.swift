import Foundation
import Observation

public enum VoiceState: Sendable, Equatable {
    case idle, connecting, listening, userSpeaking, thinking, agentSpeaking, offline
}

/// What the iPad tells the voice agent (Line `custom` events in milestone 3).
public enum VoiceEvent: Sendable, Equatable {
    /// `memberId`: the signed-in member (member memory beta, v0.14); nil for a guest.
    case tripContext(cartId: String, tripId: UUID, memberId: String? = nil)
    case cartChanged(CartChange)
    case suggestion(Suggestion)
    case dealChanged(Deal)
    case cardResponse(cardId: String, action: CardAction)
    /// v0.12 beta: the cart's amount doesn't match the list (Kart says `text` once).
    case nudge(Nudge)
    case uiAction(String)
    /// v0.14 beta: a quiet minute while a member shops; Kart may ask its one question for the trip.
    case lull
    /// v0.14 beta: "Forget me" on the screen; Kart drops what it knew at once.
    case memberForgotten
    /// v0.14 beta: 3 quiet minutes while signed in ("Still shopping, Dylan?").
    case memberIdle
}

/// What Kart is asking right now that the iPad shows as a card (the agent's `custom` messages): deals first get a
/// "want to hear them?", then one card per deal.
public enum AgentPrompt: Sendable, Equatable {
    case dealDigest(count: Int)
    case digestDeal(dealId: String, productId: String, text: String)
    /// v0.14 beta: "what do you know about me?" opens the memory screen.
    case showMemories
}

/// The hands-free conversation with Kart. `MockVoiceSession` now; `LineVoiceSession` in milestone 3.
@MainActor public protocol VoiceSession: AnyObject, Observable {
    var state: VoiceState { get }
    /// 0–1 loudness of Kart's voice; drives the avatar's mouth.
    var outputLevel: Double { get }
    var isMuted: Bool { get }
    /// Hold-to-talk (for a loud store): the mic reaches Kart only while the shopper holds the talk button.
    var holdToTalk: Bool { get set }
    var isHeld: Bool { get }
    func start(cartId: String, tripId: UUID) async
    func stop()
    func setMuted(_ muted: Bool)
    func setHeld(_ held: Bool)
    func send(_ event: VoiceEvent)
    /// Kart's current question for a card, from the agent; nil when there's none.
    var agentPrompt: AgentPrompt? { get }
    /// After a tap: hide the card until Kart sends the next one.
    func clearAgentPrompt()
}

/// Text-to-speech. Returns when the line has finished playing.
@MainActor public protocol SpeechOutput: AnyObject {
    func speak(_ text: String) async
}

/// Records what would have been said. For tests and silent screenshots.
@MainActor public final class SilentSpeech: SpeechOutput {
    public private(set) var spoken: [String] = []

    public init() {}

    public func speak(_ text: String) async {
        spoken.append(text)
    }
}
