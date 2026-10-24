import KartCore
import SwiftUI

/// What Kart remembers (member memory beta): everything on one screen, each memory one tap from forgotten.
struct MemoryView: View {
    let model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var confirmForgetAll = false

    var body: some View {
        NavigationStack {
            List {
                if let profile = model.member {
                    let memories = profile.memories
                    section("Coming up", memories.filter { $0.isUpcoming })
                    section("Likes", memories.filter { $0.kind == "preference" })
                    section("Notes", memories.filter { $0.kind == "note" })
                    if !profile.usuals.isEmpty {
                        Section("Usually buys") {
                            ForEach(profile.usuals, id: \.productId) { usual in
                                LabeledContent(usual.shortName, value: rhythm(usual))
                            }
                        }
                    }
                    section("Earlier", memories.filter { !$0.isUpcoming && ($0.kind == "event" || $0.kind == "reminder") },
                            dimmed: true)
                    if memories.isEmpty && profile.usuals.isEmpty {
                        Text("Nothing yet. Kart remembers what you buy and the plans you mention.")
                            .foregroundStyle(Theme.inkSecondary)
                    }
                }
                Section {
                    Button("Sign out") {
                        dismiss()
                        Task { try? await model.backend.signOut() }
                    }
                    .accessibilityIdentifier("memory.signOut")
                    Button("Forget me", role: .destructive) { confirmForgetAll = true }
                        .accessibilityIdentifier("memory.forgetMe")
                } footer: {
                    Text("Kart only remembers your shopping: what you buy, and plans you share for future trips. Never anything sensitive.")
                }
            }
            .accessibilityIdentifier("memory.sheet")
            .navigationTitle("What Kart remembers")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .confirmationDialog("Forget everything Kart knows about you?", isPresented: $confirmForgetAll, titleVisibility: .visible) {
                Button("Forget me", role: .destructive) {
                    dismiss()
                    Task { try? await model.backend.forgetMember() }
                }
            } message: {
                Text("Your purchase history, plans and name are deleted. You'll shop as a guest.")
            }
        }
    }

    @ViewBuilder
    private func section(_ title: String, _ memories: [MemberMemory], dimmed: Bool = false) -> some View {
        if !memories.isEmpty {
            Section(title) {
                ForEach(memories) { memory in
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(memory.text).foregroundStyle(dimmed ? Theme.inkSecondary : Theme.ink)
                            if let detail = detail(memory) {
                                Text(detail).font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                            }
                        }
                        Spacer()
                        Button("Forget") { Task { try? await model.backend.forgetMemory(id: memory.id) } }
                            .buttonStyle(.borderless)
                            .accessibilityIdentifier("memory.forget.\(memory.id)")
                    }
                }
            }
        }
    }

    private func detail(_ memory: MemberMemory) -> String? {
        var parts: [String] = []
        if let days = memory.daysUntil {
            let when = switch days {
            case 0: "today"
            case 1: "tomorrow"
            case let d where d > 1: "in \(d) days"
            case -1: "yesterday"
            default: "\(-days) days ago"
            }
            parts.append(when)
        }
        if let items = memory.items, !items.isEmpty {
            parts.append(items.map { $0.qty > 1 ? "\($0.shortName) ×\($0.qty)" : $0.shortName }.joined(separator: ", "))
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func rhythm(_ usual: MemberUsual) -> String {
        var text = usual.everyDays.map { $0 == 7 ? "every week" : "every \($0) days" } ?? "\(usual.times) times"
        if let weekday = usual.weekday { text += ", usually \(weekday)" }
        return text
    }
}
