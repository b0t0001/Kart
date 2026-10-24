import KartCore
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
                }
            }
            .statusBarHidden()
            .persistentSystemOverlays(.hidden)
            .onAppear { UIApplication.shared.isIdleTimerDisabled = true }
            .task { await world.start() }
        }
    }
}

/// Composition root: the mock backend, voice, payment and sounds behind one `AppModel`.
@MainActor @Observable
final class KartWorld {
    let scenario = UserDefaults.standard.string(forKey: "KartScenario")
    let clock = ManualClock(now: .now)
    let backend: MockKartBackend
    let voice: MockVoiceSession
    let payment = SimulatedPaymentProvider()
    let model: AppModel
    @ObservationIgnored private var started = false

    init() {
        let url = Bundle.main.url(forResource: "store", withExtension: "json")!
        let catalog = (try? Catalog.load(from: url)) ?? Catalog(layout: StoreLayout(store: StoreInfo(name: "Kart", width: 20, height: 12),
                                                                                   entrance: GridPoint(x: 0, y: 6), sections: []),
                                                                products: [], deals: [])
        let clock = clock
        backend = MockKartBackend(catalog: catalog, clock: { clock.now })
        voice = MockVoiceSession(brain: MockAgentBrain(backend: backend), backend: backend, speech: SystemSpeech())
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
        if let scenario, let demo = DemoScenario(rawValue: scenario) {
            try? await demo.apply(to: backend, clock: clock)
            model.resumeTrip()
            if backend.cart.status != .idle { voice.resume() }
        }
        model.bind()
    }
}
