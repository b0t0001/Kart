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
                    .overlay(alignment: .topLeading) {        // member memory beta: who's signed in, the demo date
                        VStack(alignment: .leading, spacing: Theme.s) {
                            MemberChip(model: model)
                            DemoDateChip(model: model)
                        }
                    }
                TripPanel(model: model)
            }
        }
        .padding(Theme.xxl)
        .overlay(alignment: .top) { ReconnectingBanner(connection: model.backend.connection) }
        .overlay(alignment: .top) { StillHereBanner(model: model) }
        .overlay { StillShoppingPrompt(model: model) }
        .task {                                               // member memory beta: a quiet minute → Kart's one question
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                model.sendLullIfDue(now: .now)
                await model.handleMemberIdle(now: .now)       // 3 min: "Still shopping, Dylan?"; 5 min: signed out
            }
        }
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

/// Member memory beta: after 3 quiet minutes signed in, "Still shopping, Dylan?"; at 5 the cart signs out.
private struct StillHereBanner: View {
    let model: AppModel

    var body: some View {
        ZStack {
            if model.stillThereAsked, let member = model.member {
                HStack(spacing: Theme.l) {
                    Text("Still shopping, \(member.member.name ?? "there")?").font(Theme.headline).foregroundStyle(Theme.ink)
                    Button("Sign out") { Task { await model.signOut() } }.buttonStyle(SecondaryButtonStyle())
                    Button("Still here") { model.noteActivity() }.buttonStyle(PrimaryButtonStyle())
                }
                .padding(.horizontal, Theme.xl).padding(.vertical, Theme.m)
                .background(Theme.surface, in: Capsule())
                .overlay(Capsule().stroke(Theme.hairline, lineWidth: 1))
                .shadow(color: .black.opacity(0.08), radius: 12, y: 4)
                .padding(.top, Theme.l)
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("member.stillHere")
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: model.stillThereAsked)
    }
}
