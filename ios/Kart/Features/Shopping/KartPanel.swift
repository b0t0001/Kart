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
            if !model.voice.holdToTalk { VoicePill(voice: model.voice) }
            // A message thread: the newest bubble always in view, older ones scroll up under a fade (and back with a
            // finger) when a card or a long turn needs the room. Never pushes the card, or the bill beside it, off a
            // smaller iPad (seen on an 11-inch).
            Thread(lines: Array(model.backend.transcript.suffix(12)))
                .frame(maxHeight: .infinity)
            if let card = model.visibleCard {
                CardView(card: card, catalog: model.backend.catalog) { action in
                    Task { await model.respond(to: card, with: action) }
                }
                .fixedSize(horizontal: false, vertical: true)
                .id(card.id)
                .transition(.asymmetric(insertion: .move(edge: .bottom).combined(with: .opacity),
                                        removal: .move(edge: .leading).combined(with: .opacity)))
            }
            if model.voice.holdToTalk { HoldToTalkButton(voice: model.voice) }
        }
        .padding(Theme.xl)
        .frame(maxHeight: .infinity, alignment: .top)
        .animation(Theme.spring, value: model.visibleCard?.id)
    }
}

/// Hold-to-talk mode (a loud store): press and hold anywhere on it to talk to Kart, let go to send. Big, low and full
/// width, so a thumb finds it while the other hand pushes the cart. Soft at rest; solid only while held, so it never
/// competes with a card's Yes.
struct HoldToTalkButton: View {
    let voice: any VoiceSession

    var body: some View {
        let held = voice.isHeld
        Label(held ? "Listening… let go to send" : "Hold to talk", systemImage: held ? "waveform" : "mic.fill")
            .font(Theme.headline)
            .foregroundStyle(held ? Color.white : Theme.brandDeep)
            .frame(maxWidth: .infinity, minHeight: 96)
            .background(held ? Theme.brand : Theme.brandSoft, in: Capsule())
            .scaleEffect(held ? 1.03 : 1)
            .contentShape(Capsule())
            .gesture(DragGesture(minimumDistance: 0)
                .onChanged { _ in if !voice.isHeld { voice.setHeld(true) } }
                .onEnded { _ in voice.setHeld(false) })
            .animation(Theme.spring, value: held)
            .accessibilityElement()
            .accessibilityLabel("Hold to talk")
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("voice.holdToTalk")
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

private struct Thread: View {
    let lines: [TranscriptLine]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                Captions(lines: lines)
                    .padding(.top, Theme.l)
            }
            .scrollIndicators(.hidden)
            .defaultScrollAnchor(.top, for: .alignment)          // a short thread sits under Kart, not down by the card
            .defaultScrollAnchor(.bottom, for: .initialOffset)
            .defaultScrollAnchor(.bottom, for: .sizeChanges)     // a card appearing keeps the newest bubble in view
            .mask(LinearGradient(stops: [.init(color: .clear, location: 0), .init(color: .black, location: 0.08)],
                                 startPoint: .top, endPoint: .bottom))
            .onChange(of: lines.last?.id) { _, id in
                guard let id else { return }
                withAnimation(Theme.spring) { proxy.scrollTo(id, anchor: .bottom) }
            }
        }
    }
}

/// The last few lines of the conversation as a message thread: Kart on the left in white, the shopper on the right in
/// the soft brand tint (solid brand stays for buttons, so a bubble never reads as something to tap).
struct Captions: View {
    let lines: [TranscriptLine]

    var body: some View {
        VStack(spacing: Theme.s) {
            ForEach(lines) { line in
                Bubble(line: line)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .frame(maxWidth: .infinity)
        .animation(Theme.spring, value: lines.map(\.id))
    }
}

private struct Bubble: View {
    let line: TranscriptLine

    private var isShopper: Bool { line.role == .user }

    var body: some View {
        let tail: CGFloat = 6
        let shape = UnevenRoundedRectangle(
            topLeadingRadius: 20, bottomLeadingRadius: isShopper ? 20 : tail,
            bottomTrailingRadius: isShopper ? tail : 20, topTrailingRadius: 20, style: .continuous)
        HStack {
            if isShopper { Spacer(minLength: Theme.xxl) }
            Text(line.text)
                .font(isShopper ? Theme.body : Theme.speech)
                .foregroundStyle(isShopper ? Theme.brandDeep : Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, Theme.l)
                .padding(.vertical, Theme.m)
                .background(isShopper ? Theme.brandSoft : Theme.surface, in: shape)
                .accessibilityLabel(isShopper ? "You said: \(line.text)" : line.text)
            if !isShopper { Spacer(minLength: Theme.xxl) }
        }
    }
}
