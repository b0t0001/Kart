import KartCore
import SwiftUI

/// Scenario "avatar": every mood side by side, plus buttons for each reaction.
struct AvatarGallery: View {
    @State private var reaction: ReactionEvent?

    var body: some View {
        VStack(spacing: Theme.xxxl) {
            HStack(spacing: Theme.xxl) {
                ForEach([("Idle", AvatarMood.idle), ("Listening", .listening), ("Thinking", .thinking), ("Speaking", .speaking)], id: \.0) { name, mood in
                    VStack(spacing: Theme.l) {
                        TimelineView(.animation) { timeline in
                            let t = timeline.date.timeIntervalSinceReferenceDate
                            AvatarView(mood: mood, level: mood == .speaking ? 0.5 + 0.5 * sin(t * 9) : 0, reaction: reaction, size: 220)
                        }
                        .frame(width: 220, height: 220)
                        Text(name).font(Theme.headline).foregroundStyle(Theme.ink)
                    }
                }
            }
            HStack(spacing: Theme.l) {
                ForEach([("Wave", AvatarReaction.wave), ("Bounce", .happyBounce), ("Tilt", .curiousTilt), ("Celebrate", .celebrate)], id: \.0) { name, kind in
                    Button(name) { reaction = ReactionEvent(reaction: kind) }
                        .buttonStyle(SecondaryButtonStyle())
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Theme.canvas)
    }
}
