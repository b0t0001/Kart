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

extension LaunchPreferences {
    public static let holdToTalkKey = "KartHoldToTalk"

    /// Hands-free by default; the debug panel's "Hold to talk" switch (for a loud store) sticks across launches.
    public static func holdToTalk(defaults: UserDefaults) -> Bool { defaults.bool(forKey: holdToTalkKey) }

    public static func persistHoldToTalk(_ on: Bool, defaults: UserDefaults) { defaults.set(on, forKey: holdToTalkKey) }

    /// Demo: Pay opens a tap-to-pay terminal (nothing is charged). Off by default; the debug panel switch sticks.
    public static let tapToPayKey = "KartTapToPay"
}
