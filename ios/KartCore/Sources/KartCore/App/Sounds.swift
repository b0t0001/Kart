import Foundation

public enum SoundCue: Sendable, Equatable {
    case added, removed, card, success
}

@MainActor public protocol SoundPlaying: AnyObject {
    func play(_ cue: SoundCue)
}
