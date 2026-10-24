import KartCore
import SwiftUI

/// The member card (member memory beta): four digits on a big keypad, then "Dylan?" to confirm. A demo sign-in,
/// not real authentication; nothing is created by a typo, and Kart greets only after "That's me".
struct MemberSignInView: View {
    let model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var digits = ""
    @State private var found: MemberLookup?

    var body: some View {
        VStack(spacing: Theme.xl) {
            MemberCard(store: model.backend.catalog.layout.store.name, digits: digits)
            if let found {
                Confirm(memberId: digits, found: found, onYes: start, onNo: { self.found = nil; digits = "" })
                    .transition(.scale(scale: 0.95).combined(with: .opacity))
            } else {
                Keypad(onDigit: press, onDelete: { if !digits.isEmpty { digits.removeLast() } })
            }
            Button("Shop as guest") {
                dismiss()
                Task { await model.startTrip() }
            }
            .buttonStyle(SecondaryButtonStyle())
            .accessibilityIdentifier("member.guest")
        }
        .padding(Theme.xxl)
        .presentationDetents([.large])
    }

    private func press(_ digit: Int) {
        guard digits.count < 4 else { return }
        digits.append(String(digit))
        guard digits.count == 4 else { return }
        let memberId = digits
        Task {
            let lookup = await model.lookUpMember(memberId) ?? MemberLookup(exists: false)
            withAnimation(Theme.spring) { found = lookup }
        }
    }

    private func start() {
        let memberId = digits
        dismiss()
        Task { await model.startTrip(memberId: memberId) }
    }
}

/// "Dylan?" for a known number (first name only), or "start a new membership?" for one Kart doesn't know.
private struct Confirm: View {
    let memberId: String
    let found: MemberLookup
    let onYes: () -> Void
    let onNo: () -> Void

    var body: some View {
        VStack(spacing: Theme.l) {
            Text(found.exists ? "\(found.name ?? "Member \(memberId)")?" : "We don't know \(memberId). Start a new membership?")
                .font(Theme.title).foregroundStyle(Theme.ink).multilineTextAlignment(.center)
            HStack(spacing: Theme.l) {
                Button(found.exists ? "Not me" : "No", action: onNo)
                    .buttonStyle(SecondaryButtonStyle())
                    .accessibilityIdentifier("member.notMe")
                Button(found.exists ? "That's me" : "Yes", action: onYes)
                    .buttonStyle(PrimaryButtonStyle())
                    .accessibilityIdentifier(found.exists ? "member.confirm" : "member.create")
            }
        }
        .frame(height: 360)
    }
}

private struct MemberCard: View {
    let store: String
    let digits: String

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.l) {
            HStack {
                Text(store).font(Theme.headline)
                Spacer()
                Text("MEMBER").font(.system(size: 15, weight: .bold, design: .rounded)).tracking(2)
            }
            HStack(spacing: Theme.m) {
                ForEach(0..<4, id: \.self) { index in
                    let digit = index < digits.count ? String(Array(digits)[index]) : ""
                    Text(digit.isEmpty ? "–" : digit)
                        .font(.system(size: 40, weight: .semibold, design: .rounded).monospacedDigit())
                        .frame(width: 64, height: 72)
                        .background(.white.opacity(digit.isEmpty ? 0.12 : 0.24), in: RoundedRectangle(cornerRadius: Theme.tileRadius))
                        .contentTransition(.numericText())
                }
            }
            .animation(Theme.spring, value: digits)
            Text("Demo sign-in · enter your member number").font(Theme.caption).opacity(0.85)
        }
        .foregroundStyle(.white)
        .padding(Theme.xl)
        .frame(width: 440)
        .background(LinearGradient(colors: [Theme.brand, Theme.brandDeep], startPoint: .topLeading, endPoint: .bottomTrailing),
                    in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .shadow(color: Theme.brandDeep.opacity(0.25), radius: 16, y: 8)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Member card, \(digits.count) of 4 digits")
    }
}

private struct Keypad: View {
    let onDigit: (Int) -> Void
    let onDelete: () -> Void

    var body: some View {
        Grid(horizontalSpacing: Theme.l, verticalSpacing: Theme.l) {
            ForEach([[1, 2, 3], [4, 5, 6], [7, 8, 9]], id: \.self) { row in
                GridRow { ForEach(row, id: \.self) { key($0) } }
            }
            GridRow {
                Color.clear.frame(width: 96, height: 72)
                key(0)
                Button(action: onDelete) {
                    Image(systemName: "delete.left").font(.system(size: 26, weight: .medium))
                        .frame(width: 96, height: 72)
                }
                .buttonStyle(.plain)
                .foregroundStyle(Theme.inkSecondary)
                .accessibilityLabel("Delete")
                .accessibilityIdentifier("member.delete")
            }
        }
    }

    private func key(_ digit: Int) -> some View {
        Button { onDigit(digit) } label: {
            Text("\(digit)").font(.system(size: 34, weight: .semibold, design: .rounded))
                .frame(width: 96, height: 72)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.tileRadius, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: Theme.tileRadius, style: .continuous).stroke(Theme.hairline))
        }
        .buttonStyle(.plain)
        .foregroundStyle(Theme.ink)
        .accessibilityIdentifier("member.key.\(digit)")
    }
}
