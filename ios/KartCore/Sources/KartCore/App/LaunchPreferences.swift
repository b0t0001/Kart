import Foundation

public enum LaunchBackend: String, Sendable {
    case mock, supabase
}

/// Which backend the app starts on. `-KartBackend mock|supabase` on launch, or the debug panel's
/// persisted choice (the venue fallback: "everything is down, use the offline demo"); a scenario always
/// means the mock, and the live backend needs a Config with a URL and key.
public enum LaunchPreferences {
    public static let backendKey = "KartBackend"

    public static func backend(defaults: UserDefaults, scenario: String?, hasConfig: Bool) -> LaunchBackend {
        guard scenario == nil, hasConfig else { return .mock }
        return defaults.string(forKey: backendKey).flatMap(LaunchBackend.init(rawValue:)) ?? .supabase
    }

    public static func persist(_ backend: LaunchBackend, defaults: UserDefaults) {
        defaults.set(backend.rawValue, forKey: backendKey)
    }
}

public enum LaunchVoice: String, Sendable { case mock, line }

extension LaunchPreferences {
    public static let voiceKey = "KartVoice"

    /// Kart's real voice (Cartesia Line) when asked for, by `-KartVoice line` or the debug panel, and only with a
    /// backend to get the voice token from. Scenarios keep the scripted voice for screenshots.
    public static func voice(defaults: UserDefaults, scenario: String?, hasConfig: Bool) -> LaunchVoice {
        guard scenario == nil, hasConfig else { return .mock }
        return defaults.string(forKey: voiceKey).flatMap(LaunchVoice.init(rawValue:)) ?? .mock
    }

    public static func persistVoice(_ voice: LaunchVoice, defaults: UserDefaults) { defaults.set(voice.rawValue, forKey: voiceKey) }
}
