import KartCore
import SwiftUI

/// Shopping: Kart on the left (40%), the trip on the right (60%).
struct ShoppingView: View {
    let model: AppModel
    let namespace: Namespace.ID

    var body: some View {
        GeometryReader { geometry in
            HStack(spacing: Theme.xl) {
                KartPanel(model: model, namespace: namespace)
                    .frame(width: (geometry.size.width - Theme.xl) * 0.4)
                TripPanel(model: model)
            }
        }
        .padding(Theme.xxl)
        .overlay(alignment: .top) { ReconnectingBanner(connection: model.backend.connection) }
        .overlay { StillShoppingPrompt(model: model) }
        .simultaneousGesture(TapGesture().onEnded { model.noteActivity() })   // any tap counts (and wakes Kart)
    }
}

private struct ReconnectingBanner: View {
    let connection: ConnectionState

    var body: some View {
        ZStack {
            if connection == .reconnecting {
                HStack(spacing: Theme.s) {
                    ProgressView()
                    Text("Reconnecting…").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                }
                .padding(.horizontal, Theme.l).frame(minHeight: 40)
                .background(Theme.surface, in: Capsule())
                .overlay(Capsule().stroke(Theme.hairline, lineWidth: 1))
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: connection)
    }
}

/// After ten quiet minutes, check whether the shopper is still here.
private struct StillShoppingPrompt: View {
    let model: AppModel

    var body: some View {
        TimelineView(.periodic(from: .now, by: 30)) { timeline in
            if model.stillShoppingPromptDue(now: timeline.date) {
                ZStack {
                    Color.black.opacity(0.18).ignoresSafeArea()
                    VStack(spacing: Theme.xl) {
                        Text("Still shopping?").font(Theme.title).foregroundStyle(Theme.ink)
                        HStack(spacing: Theme.l) {
                            Button("End trip") { Task { await model.finishTrip() } }
                                .buttonStyle(SecondaryButtonStyle())
                            Button("Yes") { model.noteActivity() }
                                .buttonStyle(PrimaryButtonStyle())
                        }
                    }
                    .padding(Theme.xxl)
                    .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
                }
                .transition(.opacity)
            }
        }
    }
}
