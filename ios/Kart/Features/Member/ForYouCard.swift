import KartCore
import SwiftUI

/// "For you" (member memory beta): a saved event list to shop, and up to three picks for this week, each with why.
struct ForYouCard: View {
    let model: AppModel

    var body: some View {
        let event = model.savedEvent
        let picks = model.forYouPicks.filter { $0.memoryId == nil || $0.memoryId != event?.id }   // the event line covers its own
        if !picks.isEmpty || event != nil {
            VStack(alignment: .leading, spacing: Theme.m) {
                HStack {
                    Label(title, systemImage: "sparkles").font(Theme.headline).foregroundStyle(Theme.brandDeep)
                    Spacer()
                    Button("Not today") { withAnimation(Theme.spring) { model.dismissForYou() } }
                        .font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                        .accessibilityIdentifier("foryou.dismiss")
                }
                if let event {
                    HStack(spacing: Theme.m) {
                        Image(systemName: "calendar").foregroundStyle(Theme.brandDeep)
                        Text(eventLine(event)).font(Theme.body).foregroundStyle(Theme.ink).lineLimit(1)
                        Spacer(minLength: 0)
                        Button("Shop it") { Task { await model.shopSavedList(event) } }
                            .buttonStyle(PrimaryButtonStyle())
                            .accessibilityLabel("Shop it: \(event.title)")
                            .accessibilityIdentifier("foryou.shopIt")
                    }
                }
                if !picks.isEmpty {
                    HStack(spacing: Theme.m) {
                        ForEach(picks) { pick in PickChip(pick: pick) { Task { await model.addPick(pick) } } }
                    }
                }
            }
            .padding(Theme.l)
            .background(Theme.brandSoft, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("foryou.card")
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    private var title: String {
        model.member?.member.name.map { "For you, \($0)" } ?? "For you"
    }

    private func eventLine(_ event: MemberMemory) -> String {
        let when = switch event.daysUntil {
        case 0: "today"
        case 1: "tomorrow"
        case let days?: "in \(days) days"
        case nil: "soon"
        }
        let count = event.items?.count ?? 0
        return "\(event.title) · \(when) · \(count) \(count == 1 ? "item" : "items") saved"
    }
}

private struct PickChip: View {
    let pick: MemberPick
    let add: () -> Void

    var body: some View {
        HStack(spacing: Theme.s) {
            VStack(alignment: .leading, spacing: 2) {
                Text(pick.shortName).font(Theme.body.weight(.semibold)).foregroundStyle(Theme.ink).lineLimit(1)
                Text(pick.reason).font(Theme.caption).foregroundStyle(Theme.inkSecondary).lineLimit(1)
            }
            Spacer(minLength: 0)
            Button(action: add) {
                Image(systemName: "plus.circle.fill").font(.system(size: 30)).foregroundStyle(Theme.brand)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Add \(pick.shortName)")
            .accessibilityIdentifier("foryou.add.\(pick.productId)")
        }
        .padding(.horizontal, Theme.m).padding(.vertical, Theme.s)
        .frame(maxWidth: .infinity, minHeight: Theme.minTap)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.tileRadius, style: .continuous))
    }
}
