import KartCore
import SwiftUI

/// The left side of Shopping: Kart, the mic pill, live captions, and one card at a time.
struct KartPanel: View {
    let model: AppModel
    let namespace: Namespace.ID

    var body: some View {
        VStack(spacing: Theme.xl) {
            AvatarView(mood: model.avatarMood, level: model.voice.outputLevel, reaction: model.reaction, size: 180)
                .matchedGeometryEffect(id: "kart", in: namespace)
            VoicePill(voice: model.voice)
            Captions(lines: Array(model.backend.transcript.suffix(3)))
            Spacer(minLength: 0)
            if let card = model.visibleCard {
                CardView(card: card, catalog: model.backend.catalog) { action in
                    Task { await model.respond(to: card, with: action) }
                }
                .id(card.id)
                .transition(.asymmetric(insertion: .move(edge: .bottom).combined(with: .opacity),
                                        removal: .move(edge: .leading).combined(with: .opacity)))
            }
        }
        .padding(Theme.xl)
        .frame(maxHeight: .infinity, alignment: .top)
        .animation(Theme.spring, value: model.visibleCard?.id)
    }
}

/// Mic state; tap to mute or unmute. Hands-free by default.
struct VoicePill: View {
    let voice: any VoiceSession

    var body: some View {
        let (text, symbol, ink, fill): (String, String, Color, Color) = switch (voice.isMuted, voice.state) {
        case (true, _): ("Muted", "mic.slash.fill", Theme.inkSecondary, Theme.hairline)
        case (_, .offline): ("Voice offline", "exclamationmark.triangle.fill", Theme.amberInk, Theme.amberSoft)
        case (_, .connecting): ("Connecting…", "ellipsis", Theme.inkSecondary, Theme.surface)
        case (_, .idle): ("Voice off", "mic.slash", Theme.inkSecondary, Theme.surface)
        default: ("Listening", "mic.fill", Theme.greenInk, Theme.greenSoft)
        }
        Button {
            voice.setMuted(!voice.isMuted)
        } label: {
            Label(text, systemImage: symbol)
                .font(Theme.headline)
                .foregroundStyle(ink)
                .padding(.horizontal, Theme.xl)
                .frame(minHeight: Theme.minTap)
                .background(fill, in: Capsule())
                .contentTransition(.symbolEffect(.replace))
        }
        .buttonStyle(.plain)
        .animation(Theme.spring, value: text)
        .accessibilityHint("Tap to mute or unmute Kart")
    }
}

/// The last few lines of the conversation: the shopper's in secondary ink, Kart's in its own voice.
struct Captions: View {
    let lines: [TranscriptLine]

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.m) {
            ForEach(lines) { line in
                Group {
                    if line.role == .user {
                        Text("You: \(line.text)")
                            .font(Theme.body)
                            .foregroundStyle(Theme.inkSecondary)
                    } else {
                        Text(line.text)
                            .font(Theme.speech)
                            .foregroundStyle(Theme.ink)
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .animation(Theme.spring, value: lines.map(\.id))
    }
}
