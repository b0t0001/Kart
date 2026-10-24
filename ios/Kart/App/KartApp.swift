import KartCore
import KartSupabase
import SwiftUI
import UIKit

@main
struct KartApp: App {
    @State private var world = KartWorld()

    var body: some Scene {
        WindowGroup {
            Group {
                if world.scenario == "avatar" {
                    AvatarGallery()
                } else {
                    RootView(model: world.model)
                        .modifier(DebugHost(world: world))
                }
            }
            .environment(\.kartStill, UserDefaults.standard.bool(forKey: "KartStill"))
            .statusBarHidden()
            .persistentSystemOverlays(.hidden)
            .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
            .task { await world.start() }
        }
    }
}

/// Supabase settings baked into Info.plist from Config.xcconfig (scripts/make-config.sh).
struct SupabaseConfig {
    let url: URL
    let anonKey: String
    let cartId: String

    static func fromInfoPlist(_ bundle: Bundle = .main) -> SupabaseConfig? {
        guard let raw = bundle.object(forInfoDictionaryKey: "KartSupabaseURL") as? String, !raw.isEmpty,
              let url = URL(string: raw), url.host != nil,
              let key = bundle.object(forInfoDictionaryKey: "KartSupabaseAnonKey") as? String, !key.isEmpty else { return nil }
        let cart = (bundle.object(forInfoDictionaryKey: "KartCartID") as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "7"
        return SupabaseConfig(url: url, anonKey: key, cartId: cart)
    }
}

/// What the debug panel can fake on either backend: the Pi's `apply_cart_event`.
@MainActor protocol DemoLevers: AnyObject {
    func simulateVision(_ type: CartEventType, productId: String?, confidence: Double, label: String) async
}

extension MockKartBackend: DemoLevers {}
extension SupabaseKartBackend: DemoLevers {}

/// Composition root. Backend: `-KartBackend mock|supabase` (default: Supabase when Config has a URL and key;
/// any `-KartScenario` forces the mock). Voice: `-KartVoice mock|line` (default: the scripted mock voice).
@MainActor @Observable
final class KartWorld {
    enum BackendKind: String { case mock, supabase }
    enum VoiceKind: String { case mock, line }

    let scenario = UserDefaults.standard.string(forKey: "KartScenario")
    let clock = ManualClock(now: .now)
    let backendKind: BackendKind
    let voiceKind: VoiceKind
    let backend: any KartBackend
    let levers: any DemoLevers
    /// Mock-only levers (merchant deals, connection) for the debug panel.
    let mock: MockKartBackend?
    let supabase: SupabaseKartBackend?
    let voice: any VoiceSession
    /// Scripted-voice levers (simulated speech, offline) for the debug panel.
    let mockVoice: MockVoiceSession?
    let payment = SimulatedPaymentProvider()
    let model: AppModel
    @ObservationIgnored private var started = false

    init() {
        let url = Bundle.main.url(forResource: "store", withExtension: "json")!
        let catalog = (try? Catalog.load(from: url)) ?? Catalog(layout: StoreLayout(store: StoreInfo(name: "Kart", width: 20, height: 12),
                                                                                   entrance: GridPoint(x: 0, y: 6), sections: []),
                                                                products: [], deals: [])
        let defaults = UserDefaults.standard
        let config = SupabaseConfig.fromInfoPlist().map { config in   // `-KartCartID` overrides (live rehearsal uses its own cart)
            SupabaseConfig(url: config.url, anonKey: config.anonKey, cartId: defaults.string(forKey: "KartCartID") ?? config.cartId)
        }
        let kind = BackendKind(rawValue: LaunchPreferences.backend(defaults: defaults, scenario: scenario,
                                                                  hasConfig: config != nil).rawValue) ?? .mock
        let clock = clock

        if kind == .supabase, let config {
            let live = SupabaseKartBackend(url: config.url, anonKey: config.anonKey, cartId: config.cartId, layout: catalog.layout)
            supabase = live
            mock = nil
            backend = live
            levers = live
            backendKind = .supabase
        } else {
            let fake = MockKartBackend(catalog: catalog, clock: { clock.now })
            mock = fake
            supabase = nil
            backend = fake
            levers = fake
            backendKind = .mock
        }

        let requestedVoice = defaults.string(forKey: "KartVoice").flatMap(VoiceKind.init(rawValue:))
        if requestedVoice == .line, let config {
            voice = LineVoiceSession(tokens: SupabaseVoiceTokenProvider(url: config.url, anonKey: config.anonKey),
                                     transport: WebSocketTransport(), audio: EngineAudio())
            mockVoice = nil
            voiceKind = .line
        } else {
            let scripted = MockVoiceSession(brain: MockAgentBrain(backend: backend), backend: backend, speech: SystemSpeech(),
                                            animatesLevel: !defaults.bool(forKey: "KartStill"))
            voice = scripted
            mockVoice = scripted
            voiceKind = .mock
        }
        model = AppModel(backend: backend, voice: voice, payment: payment, sounds: SoundPlayer(), clock: { clock.now })
    }

    func start() async {
        guard !started else { return }
        started = true
        Task { @MainActor [clock] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(1))
                if clock.now < .now { clock.now = .now }
            }
        }
        if let scenario, let demo = DemoScenario(rawValue: scenario), let mock {
            try? await demo.apply(to: mock, clock: clock)
        }
        if let supabase { await supabase.start() }
        if backend.cart.status != .idle {             // a scenario, or an app relaunched mid-trip
            model.resumeTrip()
            if let mockVoice { mockVoice.resume() } else { await model.retryVoice() }
        }
        model.bind()
    }
}
