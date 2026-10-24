import Foundation

public enum AvatarMood: Sendable, Equatable {
    case idle, listening, thinking, speaking

    public init(_ voice: VoiceState) {
        switch voice {
        case .idle, .connecting, .offline, .paused: self = .idle
        case .listening, .userSpeaking: self = .listening
        case .thinking: self = .thinking
        case .agentSpeaking: self = .speaking
        }
    }
}

public enum AvatarReaction: Sendable, Equatable {
    case wave, happyBounce, curiousTilt, celebrate
}
