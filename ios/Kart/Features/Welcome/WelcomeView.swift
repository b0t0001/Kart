import KartCore
import SwiftUI

/// The parked cart: Kart breathing and blinking, one obvious thing to do. The mic is off here.
struct WelcomeView: View {
    let model: AppModel
    let namespace: Namespace.ID

    var body: some View {
        VStack(spacing: Theme.xxl) {
            AvatarView(mood: .idle, reaction: model.reaction, size: 360)
                .matchedGeometryEffect(id: "kart", in: namespace)
            VStack(spacing: Theme.m) {
                Text("Tap to start shopping")
                    .font(Theme.title)
                    .foregroundStyle(Theme.ink)
                Label("The mic stays off until you start.", systemImage: "mic.slash")
                    .font(Theme.caption)
                    .foregroundStyle(Theme.inkSecondary)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .onTapGesture { Task { await model.startTrip() } }
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isButton)
        .accessibilityLabel("Start shopping")
        .accessibilityIdentifier("welcome.start")
    }
}

/// Kart introduces itself, centered, before gliding into the shopping layout.
struct GreetingView: View {
    let model: AppModel
    let namespace: Namespace.ID

    var body: some View {
        VStack(spacing: Theme.xxl) {
            AvatarView(mood: model.avatarMood, level: model.voice.outputLevel, reaction: model.reaction, size: 300)
                .matchedGeometryEffect(id: "kart", in: namespace)
            if let line = model.backend.transcript.last(where: { $0.role == .agent }) {
                Text(line.text)
                    .font(Theme.speech)
                    .foregroundStyle(Theme.ink)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 640)
                    .transition(.opacity)
            }
            VoicePill(voice: model.voice)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(Theme.spring, value: model.backend.transcript.count)
    }
}
