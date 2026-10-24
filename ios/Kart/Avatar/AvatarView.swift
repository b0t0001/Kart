import KartCore
import SwiftUI

/// Kart's face: breathes and blinks, reacts to the conversation, and moves its mouth with its voice.
struct AvatarView: View {
    let mood: AvatarMood
    var level: Double = 0
    var reaction: ReactionEvent? = nil
    var size: CGFloat = 220

    @State private var rotation: Double = 0
    @State private var lift: CGFloat = 0
    @State private var confetti: UUID?

    var body: some View {
        TimelineView(.animation) { timeline in
            let t = timeline.date.timeIntervalSinceReferenceDate
            face(t: t)
        }
        .frame(width: size, height: size)
        .rotationEffect(.degrees(rotation))
        .offset(y: lift)
        .overlay { ConfettiBurst(trigger: confetti, count: 24, spread: size * 1.4) }
        .onChange(of: reaction?.id) { _, _ in
            if let reaction { play(reaction.reaction) }
        }
        .accessibilityLabel("Kart")
    }

    private func face(t: TimeInterval) -> some View {
        let breathe = 1 + 0.015 * sin(2 * .pi * t / 4)
        let blinking = t.truncatingRemainder(dividingBy: 4.3) < 0.12 && mood != .speaking
        let eyeHeight = size * 0.20 * (blinking ? 0.1 : (mood == .listening ? 1.12 : 1))
        let eyeOffset = mood == .thinking ? CGSize(width: size * 0.03, height: -size * 0.04) : .zero

        return ZStack {
            RoundedRectangle(cornerRadius: size * 0.3, style: .continuous)
                .fill(Theme.brand)
            HStack(spacing: size * 0.20) {
                eye(height: eyeHeight)
                eye(height: eyeHeight)
            }
            .offset(x: eyeOffset.width, y: -size * 0.08 + eyeOffset.height)
            mouth
                .offset(y: size * 0.20)
        }
        .scaleEffect(breathe)
        .animation(.easeOut(duration: 0.12), value: mood)
    }

    private func eye(height: CGFloat) -> some View {
        Capsule()
            .fill(Theme.brandDeep)
            .frame(width: size * 0.12, height: height)
    }

    @ViewBuilder private var mouth: some View {
        if mood == .speaking {
            Capsule()
                .fill(Theme.brandDeep)
                .frame(width: size * 0.28, height: size * (0.04 + 0.12 * min(max(level, 0), 1)))
        } else {
            Smile()
                .stroke(Theme.brandDeep, style: StrokeStyle(lineWidth: size * 0.045, lineCap: .round))
                .frame(width: size * 0.30, height: size * 0.10)
        }
    }

    private func play(_ reaction: AvatarReaction) {
        Task { @MainActor in
            switch reaction {
            case .wave:
                for angle in [8.0, -8, 8, -8, 0] {
                    withAnimation(.easeInOut(duration: 0.16)) { rotation = angle }
                    try? await Task.sleep(for: .milliseconds(160))
                }
            case .happyBounce:
                withAnimation(.spring(response: 0.25, dampingFraction: 0.5)) { lift = -size * 0.06 }
                try? await Task.sleep(for: .milliseconds(220))
                withAnimation(Theme.spring) { lift = 0 }
            case .curiousTilt:
                withAnimation(Theme.spring) { rotation = 10 }
                try? await Task.sleep(for: .milliseconds(1200))
                withAnimation(Theme.spring) { rotation = 0 }
            case .celebrate:
                confetti = UUID()
                withAnimation(.spring(response: 0.25, dampingFraction: 0.45)) { lift = -size * 0.08 }
                try? await Task.sleep(for: .milliseconds(260))
                withAnimation(Theme.spring) { lift = 0 }
            }
        }
    }
}

private struct Smile: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY), control: CGPoint(x: rect.midX, y: rect.maxY * 1.6))
        return path
    }
}
