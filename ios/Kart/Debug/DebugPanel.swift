import KartCore
import SwiftUI

/// Everything needed to run the demo by hand: fake the Pi, put words in the shopper's mouth, play the merchant.
struct DebugPanel: View {
    @AppStorage(LaunchPreferences.tapToPayKey) private var tapToPay = false
    let world: KartWorld
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text(world.backendKind == .supabase ? "Backend: Supabase (live)" : "Backend: built-in mock")
                    Text(world.voiceKind == .line ? "Voice: Cartesia Line" : "Voice: scripted Kart (on-device speech)")
                    if world.backendKind == .supabase {
                        row("Use offline demo mode (relaunch)", id: "debug.useMock") {
                            LaunchPreferences.persist(.mock, defaults: .standard)
                        }
                    } else if SupabaseConfig.fromInfoPlist() != nil {
                        row("Use the live backend (relaunch)", id: "debug.useLive") {
                            LaunchPreferences.persist(.supabase, defaults: .standard)
                        }
                    }
                    if world.voiceKind == .mock, SupabaseConfig.fromInfoPlist() != nil {
                        row("Use Kart's real voice, Cartesia (relaunch)", id: "debug.useLineVoice") {
                            LaunchPreferences.persistVoice(.line, defaults: .standard)
                        }
                    } else if world.voiceKind == .line {
                        row("Use the scripted voice (relaunch)", id: "debug.useMockVoice") {
                            LaunchPreferences.persistVoice(.mock, defaults: .standard)
                        }
                    }
                    Toggle("Quantity nudges (beta)", isOn: Binding(
                        get: { world.backend.cart.quantityNudgesOn },
                        set: { on in Task { try? await world.backend.setFeature("quantity_nudges", on: on) } }))
                        .accessibilityIdentifier("debug.quantityNudges")
                    Toggle("Member memory (beta)", isOn: Binding(
                        get: { world.backend.cart.memberMemoryOn },
                        set: { on in Task { try? await world.backend.setFeature("member_memory", on: on) } }))
                        .accessibilityIdentifier("debug.memberMemory")
                    Toggle("Hold to talk (for a loud store)", isOn: Binding(
                        get: { world.voice.holdToTalk },
                        set: { world.voice.holdToTalk = $0; LaunchPreferences.persistHoldToTalk($0, defaults: .standard) }))
                        .accessibilityIdentifier("debug.holdToTalk")
                    Toggle("Tap-to-pay terminal (demo, no charge)", isOn: $tapToPay)
                        .accessibilityIdentifier("debug.tapToPay")
                    if let error = world.supabase?.lastError {
                        Text("Last backend error: \(error)").foregroundStyle(.red).font(.footnote)
                    }
                }
                if world.backend.cart.memberMemoryOn {
                    Section("Demo date") {
                        Text(world.model.demoDateLabel ?? "Today (real date)")
                        row("Today", id: "debug.date.today") { await world.model.jumpDemoDate(to: .today) }
                        row("+1 day", id: "debug.date.plus1") { await world.model.jumpDemoDate(to: .plusDays(1)) }
                        row("+1 week", id: "debug.date.plus7") { await world.model.jumpDemoDate(to: .plusDays(7)) }
                        if let label = world.model.fastForwardLabel {     // Act 2: a new trip, back on Welcome
                            row(label, id: "debug.date.beforeEvent") { await world.model.fastForward() }
                        }
                    }
                }
                Section("Trip") {
                    row("New trip", id: "debug.newTrip") { await world.model.startTrip() }
                    row("Go to checkout", id: "debug.checkout") { await world.model.beginCheckout() }
                    row("End trip", id: "debug.endTrip") { await world.model.finishTrip() }
                    if let mock = world.mock {
                        Toggle("Backend reconnecting", isOn: Binding(
                            get: { mock.connection == .reconnecting },
                            set: { mock.setConnection($0 ? .reconnecting : .online) }))
                    }
                }
                if let voice = world.mockVoice {
                    Section("You say") {
                        ForEach(Array(DemoScript.userLines.enumerated()), id: \.offset) { index, line in
                            row("“\(line)”", id: "debug.say.\(index)") { await voice.simulateUserSays(line) }
                        }
                        Toggle("Mute", isOn: Binding(get: { voice.isMuted }, set: { voice.setMuted($0) }))
                        Toggle("Voice offline", isOn: Binding(get: { voice.forcedOffline }, set: { voice.forcedOffline = $0 }))
                            .accessibilityIdentifier("debug.voiceOffline")
                    }
                }
                Section("Merchant") {
                    if let mock = world.mock {
                        row("Remove Parmesan deal", id: "debug.removeParmDeal") { await mock.removeDeal(id: DemoScript.parmesanDeal.id) }
                        row("Create Parmesan $1 off", id: "debug.createParmDeal") { await mock.pushDeal(DemoScript.parmesanDeal) }
                        row("Push Bananas 50¢ off", id: "debug.pushBananas") { await mock.pushDeal(DemoScript.bananaDeal) }
                        row("Remove Bananas deal", id: "debug.removeBananas") { await mock.removeDeal(id: DemoScript.bananaDeal.id) }
                    } else {
                        Text("On the live backend, deals come from the merchant console (or `backend/cart.py deal kirkland-parmesan 1`).")
                            .foregroundStyle(.secondary)
                    }
                }
                Section("Payment") {
                    Toggle("Force payment failure", isOn: Binding(get: { world.payment.forceFailure }, set: { world.payment.forceFailure = $0 })).accessibilityIdentifier("debug.forceFailure")
                }
                Section("Cart (what the Pi would send)") {
                    row("Add unknown thing", id: "debug.unknown") {
                        await world.levers.simulateVision(.added, productId: nil, confidence: 0.3, label: "blue umbrella")
                    }
                    ForEach(world.backend.catalog.products) { product in
                        HStack(spacing: Theme.m) {
                            ProductTile(category: product.category, size: 36)
                            Text(product.shortName)
                            Spacer()
                            button("Add", id: "debug.add.\(product.id)") {
                                await world.levers.simulateVision(.added, productId: product.id, confidence: 0.95, label: product.name)
                            }
                            button("Add unsure", id: "debug.unsure.\(product.id)") {
                                await world.levers.simulateVision(.added, productId: nil, confidence: 0.42, label: product.name)
                            }
                            button("Remove", id: "debug.remove.\(product.id)") {
                                await world.levers.simulateVision(.removed, productId: product.id, confidence: 0.95, label: product.name)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Demo controls")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Close") { dismiss() }.accessibilityIdentifier("debug.close")
                }
            }
        }
    }

    private func row(_ title: String, id: String, _ action: @escaping () async -> Void) -> some View {
        Button(title) { Task { await action() } }.accessibilityIdentifier(id)
    }

    private func button(_ title: String, id: String, _ action: @escaping () async -> Void) -> some View {
        Button(title) { Task { await action() } }
            .buttonStyle(.bordered)
            .accessibilityIdentifier(id)
    }
}

/// Opens the panel with a three-finger long press, or a corner button when launched with `-KartDebugButton YES`.
struct DebugHost: ViewModifier {
    let world: KartWorld
    @State private var open = false

    func body(content: Content) -> some View {
        content
            .background(ThreeFingerPress { open = true })
            .overlay(alignment: .topTrailing) {
                if UserDefaults.standard.bool(forKey: "KartDebugButton") {
                    Button { open = true } label: {
                        Image(systemName: "slider.horizontal.3").font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(Theme.inkSecondary).frame(width: 44, height: 44)
                            .background(Theme.surface.opacity(0.9), in: Circle())
                    }
                    .accessibilityIdentifier("debug.open")
                    .padding(Theme.s)
                }
            }
            .sheet(isPresented: $open) { DebugPanel(world: world) }
    }
}
