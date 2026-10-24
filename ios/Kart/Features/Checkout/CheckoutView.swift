import KartCore
import SwiftUI

/// The bill: unconfirmed items first, every line with its full name, then one way to pay.
struct CheckoutView: View {
    let model: AppModel
    @State private var pulse = false

    private var confirmCards: [Card] {
        model.cards.filter { if case .confirmItem = $0.kind { true } else { false } }
    }

    var body: some View {
        let cart = model.backend.cart
        GeometryReader { geometry in
        HStack(alignment: .top, spacing: Theme.xxl) {
            VStack(alignment: .leading, spacing: Theme.l) {
                Text("Your bill").font(Theme.title).foregroundStyle(Theme.ink)
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(spacing: Theme.m) {
                            ForEach(confirmCards) { card in
                                CardView(card: card, catalog: model.backend.catalog) { action in
                                    Task { await model.respond(to: card, with: action) }
                                }
                                .overlay(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                                    .stroke(Theme.amber, lineWidth: pulse ? 4 : 0))
                                .id("unresolved-\(card.id)")
                                .transition(.move(edge: .top).combined(with: .opacity))
                            }
                            ForEach(cart.items) { item in
                                BillLine(item: item, category: model.backend.catalog.product(item.productId)?.category)
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                    .onChange(of: model.highlightUnresolved) { _, highlight in
                        guard highlight, let first = confirmCards.first else { return }
                        withAnimation(Theme.spring) { proxy.scrollTo("unresolved-\(first.id)", anchor: .top) }
                        Task { @MainActor in
                            for _ in 0..<2 {
                                withAnimation(.easeInOut(duration: 0.25)) { pulse = true }
                                try? await Task.sleep(for: .milliseconds(280))
                                withAnimation(.easeInOut(duration: 0.25)) { pulse = false }
                                try? await Task.sleep(for: .milliseconds(280))
                            }
                        }
                    }
                }
            }
            .frame(width: (geometry.size.width - Theme.xxl) * 0.6)

            PaySummary(model: model, unresolved: confirmCards.count)
                .frame(width: (geometry.size.width - Theme.xxl) * 0.4)
        }
        }
        .padding(Theme.xxl)
        .animation(Theme.spring, value: confirmCards.map(\.id))
        .overlay { PayOverlay(state: model.paymentState) { Task { await model.pay() } } }
    }
}

private struct BillLine: View {
    let item: CartItem
    let category: String?

    var body: some View {
        HStack(spacing: Theme.l) {
            ProductTile(category: category, size: 56)
            VStack(alignment: .leading, spacing: Theme.xs) {
                Text(item.name).font(Theme.body).foregroundStyle(Theme.ink).lineLimit(2)
                HStack(spacing: Theme.s) {
                    if item.qty > 1 {
                        Text("×\(item.qty)").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    }
                    if let deal = item.dealLabel {
                        Text(deal)
                            .font(Theme.caption).foregroundStyle(Theme.greenInk)
                            .padding(.horizontal, Theme.s).padding(.vertical, 2)
                            .background(Theme.greenSoft, in: Capsule())
                    }
                }
            }
            Spacer(minLength: Theme.m)
            VStack(alignment: .trailing, spacing: Theme.xs) {
                Text(Money.format(item.price * Decimal(item.qty))).font(Theme.headline).monospacedDigit().foregroundStyle(Theme.ink)
                if let list = item.listPrice, list > item.price {
                    Text(Money.format(list * Decimal(item.qty)))
                        .font(Theme.caption).strikethrough().foregroundStyle(Theme.inkSecondary)
                }
            }
        }
        .padding(.horizontal, Theme.xl)
        .frame(minHeight: 88)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.tileRadius, style: .continuous))
    }
}

private struct PaySummary: View {
    let model: AppModel
    let unresolved: Int

    var body: some View {
        let cart = model.backend.cart
        VStack(alignment: .leading, spacing: Theme.xl) {
            HStack {
                Text("\(cart.itemCount) \(cart.itemCount == 1 ? "item" : "items")").font(Theme.body).foregroundStyle(Theme.inkSecondary)
                Spacer()
            }
            if let savings = cart.savings, savings > 0 {
                HStack {
                    Text("Saved").font(Theme.headline).foregroundStyle(Theme.green)
                    Spacer()
                    Text(Money.format(savings)).font(Theme.headline).monospacedDigit().foregroundStyle(Theme.green)
                }
            }
            Divider().overlay(Theme.hairline)
            VStack(alignment: .leading, spacing: Theme.xs) {
                Text("Total").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                Text(Money.format(cart.total)).font(Theme.display).monospacedDigit().foregroundStyle(Theme.ink)
            }
            Spacer(minLength: Theme.xl)
            Button {
                Task { await model.pay() }
            } label: {
                Text(unresolved == 0 ? "Pay \(Money.format(cart.total))"
                                     : "Confirm \(unresolved) \(unresolved == 1 ? "item" : "items") first")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(PayButtonStyle(ready: unresolved == 0))
            Button {
                Task { await model.resumeShopping() }
            } label: {
                Text("Keep shopping").frame(maxWidth: .infinity)
            }
            .buttonStyle(SecondaryButtonStyle())
        }
        .padding(Theme.xxl)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

/// Filled when the bill is ready; outlined while a confirm card's own "Yes" is the action to take.
private struct PayButtonStyle: ButtonStyle {
    let ready: Bool

    func makeBody(configuration: Configuration) -> some View {
        if ready {
            PrimaryButtonStyle().makeBody(configuration: configuration)
        } else {
            SecondaryButtonStyle().makeBody(configuration: configuration)
        }
    }
}
