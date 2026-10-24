import KartCore
import SwiftUI

/// Who's signed in (member memory beta); a tap opens what Kart remembers.
struct MemberChip: View {
    let model: AppModel

    var body: some View {
        if let member = model.member {
            let name = member.member.name ?? "Member \(member.member.memberId)"
            Button { model.openMemories() } label: {
                HStack(spacing: Theme.s) {
                    Text(String(name.prefix(1)).uppercased())
                        .font(.system(size: 18, weight: .bold, design: .rounded)).foregroundStyle(.white)
                        .frame(width: 36, height: 36)
                        .background(Theme.brand, in: Circle())
                    Text(name).font(Theme.headline).foregroundStyle(Theme.ink)
                }
                .padding(.leading, Theme.xs).padding(.trailing, Theme.l)
                .frame(minHeight: 44)
                .background(Theme.surface, in: Capsule())
                .overlay(Capsule().stroke(Theme.hairline, lineWidth: 1))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("\(name). What Kart remembers")
            .accessibilityIdentifier("member.chip")
            .sheet(isPresented: Binding(get: { model.showingMemories }, set: { if !$0 { model.closeMemories() } })) {
                MemoryView(model: model)                       // also opened by Kart: "what do you know about me?"
            }
        }
    }
}

/// While the demo fast-forward is set: the date the cart is pretending it is, flipping as it changes.
struct DemoDateChip: View {
    let model: AppModel

    var body: some View {
        if let label = model.demoDateLabel {
            Label(label, systemImage: "calendar.badge.clock")
                .font(Theme.caption.weight(.medium))
                .foregroundStyle(Theme.amberInk)
                .padding(.horizontal, Theme.m).frame(minHeight: 36)
                .background(Theme.amberSoft, in: Capsule())
                .contentTransition(.numericText())
                .animation(Theme.spring, value: label)
                .accessibilityIdentifier("demo.date")
        }
    }
}
