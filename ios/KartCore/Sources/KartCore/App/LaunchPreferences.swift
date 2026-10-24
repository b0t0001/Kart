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
