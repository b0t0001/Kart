import Foundation

public enum VoiceState: Sendable, Equatable {
    case idle, connecting, listening, userSpeaking, thinking, agentSpeaking, offline
}
