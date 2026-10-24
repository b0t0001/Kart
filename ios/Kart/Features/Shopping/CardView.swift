import KartCore
import SwiftUI

/// One card: a confirm question (amber), a deal (brand), or an offline notice.
struct CardView: View {
    let card: Card
    let catalog: Catalog
    let onAction: (CardAction) -> Void

    @State private var choosing = false
    @State private var pulse = false
    @State private var burst: UUID?

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.l) {
            HStack(spacing: Theme.l) {
                if let tile = tileCategory {
                    ProductTile(category: tile, size: 56)
                }
                Text(card.title)
                    .font(Theme.headline)
                    .foregroundStyle(titleInk)
                    .fixedSize(horizontal: false, vertical: true)
            }
            if choosing, case .confirmItem(_, let candidates) = card.kind {
                candidatePicker(candidates)
            } else {
                actionRow
            }
        }
        .padding(Theme.xl)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(fill, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous).stroke(border, lineWidth: 1.5))
        .scaleEffect(pulse ? 1.04 : 1)
        .overlay(alignment: .top) { ConfettiBurst(trigger: burst, count: 10, spread: 160, duration: 1.0) }
        .onAppear(perform: popIfDeal)
    }

    private var actionRow: some View {
        HStack(spacing: Theme.m) {
            ForEach(Array(card.actions.enumerated()), id: \.offset) { index, action in
                let primary = index == 0 && (action == .yes || action == .addIt || action == .goGetIt || action == .goGetThem)
                Button(action.title) {
                    if action == .somethingElse { withAnimation(Theme.spring) { choosing = true } } else { onAction(action) }
                }
                .buttonStyle(CardButtonStyle(primary: primary))
                .accessibilityIdentifier("card.\(action.title)")
            }
        }
    }

    private func candidatePicker(_ candidates: [Product]) -> some View {
        HStack(spacing: Theme.m) {
            ForEach(candidates) { product in
                Button {
                    onAction(.choose(productId: product.id))
                } label: {
                    HStack(spacing: Theme.s) {
                        ProductTile(category: product.category, size: 36)
                        Text(product.shortName)
                    }
                }
                .buttonStyle(CardButtonStyle(primary: false))
            }
            Button(CardAction.remove.title) { onAction(.remove) }
                .buttonStyle(CardButtonStyle(primary: false))
        }
    }

    private func popIfDeal() {
        switch card.kind {
        case .deal, .newDeal:
            burst = UUID()
            withAnimation(.spring(response: 0.3, dampingFraction: 0.5)) { pulse = true }
            Task { @MainActor in
                try? await Task.sleep(for: .milliseconds(300))
                withAnimation(Theme.spring) { pulse = false }
            }
        case .confirmItem, .offline, .nudge:
            break
        }
    }

    private var tileCategory: String? {
        switch card.kind {
        case .confirmItem(_, let candidates): candidates.first?.category ?? "unknown"
        case .deal(let suggestion): catalog.product(suggestion.productId)?.category
        case .newDeal(let deal): catalog.product(deal.productId)?.category
        case .nudge(let nudge): catalog.product(nudge.productId)?.category
        case .offline: nil
        }
    }

    private var fill: Color {
        switch card.kind {
        case .confirmItem: Theme.amberSoft
        case .deal, .newDeal, .nudge: Theme.brandSoft
        case .offline: Theme.surface
        }
    }

    private var border: Color {
        switch card.kind {
        case .confirmItem: Theme.amber
        case .deal, .newDeal, .nudge: Theme.brand.opacity(0.35)
        case .offline: Theme.hairline
        }
    }

    private var titleInk: Color {
        switch card.kind {
        case .confirmItem: Theme.amberInk
        case .deal, .newDeal, .nudge: Theme.brandDeep
        case .offline: Theme.ink
        }
    }
}

private struct CardButtonStyle: ButtonStyle {
    let primary: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.headline)
            .lineLimit(1)
            .minimumScaleFactor(0.75)
            .foregroundStyle(primary ? .white : Theme.ink)
            .padding(.horizontal, Theme.m)
            .frame(minHeight: Theme.minTap)
            .frame(maxWidth: .infinity)
            .background(primary ? Theme.brand : Theme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(primary ? .clear : Theme.hairline, lineWidth: 1.5))
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .animation(Theme.spring, value: configuration.isPressed)
    }
}
