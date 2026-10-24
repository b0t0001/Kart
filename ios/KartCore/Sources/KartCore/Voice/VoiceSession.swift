import Foundation
import Observation

public enum VoiceState: Sendable, Equatable {
    case idle, connecting, listening, userSpeaking, thinking, agentSpeaking, offline
}

/// What the iPad tells the voice agent (Line `custom` events in milestone 3).
public enum VoiceEvent: Sendable, Equatable {
    case tripContext(cartId: String, tripId: UUID)
    case cartChanged(CartChange)
    case suggestion(Suggestion)
    case dealChanged(Deal)
    case cardResponse(cardId: String, action: CardAction)
    case uiAction(String)
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
