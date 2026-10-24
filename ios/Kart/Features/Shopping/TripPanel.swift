import KartCore
import SwiftUI

/// The right side of Shopping: next stop, your list beside your cart, and the total that never scrolls away.
struct TripPanel: View {
    let model: AppModel

    private var cart: CartState { model.backend.cart }
    private var catalog: Catalog { model.backend.catalog }

    var body: some View {
        VStack(spacing: Theme.xl) {
            NextStopCard(model: model)
            HStack(alignment: .top, spacing: Theme.xl) {
                ListColumn(plan: cart.plan, catalog: catalog)
                CartColumn(items: cart.items, unresolved: model.unresolvedCount, catalog: catalog)
            }
            .frame(maxHeight: .infinity)
            TotalFooter(model: model)
        }
        .overlay(alignment: .top) { CelebrationToast(model: model) }
    }
}

private struct NextStopCard: View {
    let model: AppModel

    var body: some View {
        let cart = model.backend.cart
        let stop = model.nextStop
        HStack(spacing: Theme.xl) {
            StoreMapView(layout: model.backend.catalog.layout, highlight: stop?.sectionId, here: cart.location?.section)
                .frame(width: 240, height: 144)
            VStack(alignment: .leading, spacing: Theme.s) {
                if let stop {
                    Text("Next stop").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    Text(stop.text).font(Theme.title).foregroundStyle(Theme.ink)
                        .contentTransition(.opacity)
                } else if cart.plan.isEmpty {
                    Text("Next stop").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    Text("Tell Kart what you're shopping for").font(Theme.headline).foregroundStyle(Theme.ink)
                } else {
                    Label("Everything on your list is in the cart", systemImage: "checkmark.circle.fill")
                        .font(Theme.headline).foregroundStyle(Theme.greenInk)
                }
                Text(NextStop.hereText(cart: cart, catalog: model.backend.catalog))
                    .font(Theme.caption).foregroundStyle(Theme.inkSecondary)
            }
            Spacer(minLength: 0)
        }
        .padding(Theme.xl)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .animation(Theme.spring, value: stop)
    }
}

private struct ListColumn: View {
    let plan: [PlanItem]
    let catalog: Catalog

    var body: some View {
        Column(title: "Your list") {
            if plan.isEmpty {
                Text("Say what you need, like \u{201C}pasta dinner for four.\u{201D}")
                    .font(Theme.body).foregroundStyle(Theme.inkSecondary)
                    .padding(.vertical, Theme.m)
            }
            ForEach(plan) { line in
                HStack(spacing: Theme.m) {
                    Image(systemName: line.done ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 26, weight: .medium))
                        .foregroundStyle(line.done ? Theme.green : Theme.hairline)
                    Text(line.name ?? catalog.product(line.productId)?.shortName ?? line.reason)
                        .font(Theme.body)
                        .foregroundStyle(line.done ? Theme.inkSecondary : Theme.ink)
                        .lineLimit(1)
                    Spacer(minLength: Theme.s)
                    if line.inStock == false {
                        Text("Out of stock").font(Theme.caption).foregroundStyle(Theme.amberInk)
                    } else if !line.done {
                        if let deal = line.dealLabel { DealBadge(label: deal) }
                        if let aisle = line.aisle {
                            Text(aisle).font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                        }
                    }
                }
                .frame(minHeight: Theme.minTap)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: plan)
    }
}

/// "$3 off", on a list row (a deal on something you planned) or a cart row (what you're paying).
private struct DealBadge: View {
    let label: String

    var body: some View {
        Text(label)
            .font(Theme.caption).foregroundStyle(Theme.greenInk)
            .padding(.horizontal, Theme.s).padding(.vertical, 2)
            .background(Theme.greenSoft, in: Capsule())
    }
}

private struct CartColumn: View {
    let items: [CartItem]
    let unresolved: Int
    let catalog: Catalog

    var body: some View {
        Column(title: "In your cart") {
            if items.isEmpty && unresolved == 0 {
                Text("Items appear here as they go in.")
                    .font(Theme.body).foregroundStyle(Theme.inkSecondary)
                    .padding(.vertical, Theme.m)
            }
            ForEach(0..<unresolved, id: \.self) { _ in
                HStack(spacing: Theme.m) {
                    ProductTile(category: nil, size: 44)
                    Text("Something new").font(Theme.body).foregroundStyle(Theme.amberInk)
                    Spacer()
                    Image(systemName: "questionmark.circle.fill").font(.system(size: 26)).foregroundStyle(Theme.amber)
                }
                .frame(minHeight: Theme.minTap)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
            ForEach(items) { item in
                HStack(spacing: Theme.m) {
                    ProductTile(category: catalog.product(item.productId)?.category, size: 44)
                    Text(item.shortName ?? catalog.product(item.productId)?.shortName ?? item.name)
                        .font(Theme.body).foregroundStyle(Theme.ink).lineLimit(1).minimumScaleFactor(0.85)
                    if item.qty > 1 {
                        Text("×\(item.qty)").font(Theme.body).foregroundStyle(Theme.inkSecondary)
                    }
                    Spacer(minLength: Theme.s)
                    if let deal = item.dealLabel { DealBadge(label: deal) }
                    Text(Money.format(item.price * Decimal(item.qty)))
                        .font(Theme.body).monospacedDigit().foregroundStyle(Theme.ink)
                        .contentTransition(.numericText())
                }
                .frame(minHeight: Theme.minTap)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: items)
        .animation(Theme.spring, value: unresolved)
    }
}

private struct Column<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: Theme.s) {
            Text(title).font(Theme.caption).foregroundStyle(Theme.inkSecondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 0) { content }
            }
            .scrollIndicators(.hidden)
        }
        .padding(Theme.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

private struct TotalFooter: View {
    let model: AppModel

    var body: some View {
        let cart = model.backend.cart
        HStack(alignment: .bottom) {
            VStack(alignment: .leading, spacing: Theme.xs) {
                Text("Estimated total").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                HStack(alignment: .firstTextBaseline, spacing: Theme.l) {
                    Text(Money.format(cart.total))
                        .font(Theme.display).monospacedDigit().foregroundStyle(Theme.ink)
                        .contentTransition(.numericText(value: NSDecimalNumber(decimal: cart.total).doubleValue))
                    if let savings = cart.savings, savings > 0 {
                        Text("Saved \(Money.format(savings))")
                            .font(Theme.headline).foregroundStyle(Theme.green)
                            .transition(.opacity)
                    }
                }
            }
            Spacer()
            Button {
                Task { await model.beginCheckout() }
            } label: {
                Label("Check out", systemImage: "arrow.right").labelStyle(TrailingIconLabelStyle())
                    .frame(minWidth: 220)
            }
            .buttonStyle(PrimaryButtonStyle())
            .accessibilityIdentifier("checkout.button")
        }
        .animation(Theme.spring, value: cart.total)
    }
}

private struct TrailingIconLabelStyle: LabelStyle {
    func makeBody(configuration: Configuration) -> some View {
        HStack(spacing: Theme.s) {
            configuration.title
            configuration.icon
        }
    }
}

/// "Parmesan just dropped $3. You saved." slides down for four seconds.
private struct CelebrationToast: View {
    let model: AppModel

    var body: some View {
        ZStack {
            if let text = model.celebration {
                Label(text, systemImage: "sparkles")
                    .font(Theme.headline).foregroundStyle(Theme.greenInk)
                    .padding(.horizontal, Theme.xl).frame(minHeight: 56)
                    .background(Theme.greenSoft, in: Capsule())
                    .overlay(Capsule().stroke(Theme.green.opacity(0.3), lineWidth: 1))
                    .transition(.move(edge: .top).combined(with: .opacity))
                    .task(id: text) {
                        try? await Task.sleep(for: .seconds(4))
                        model.clearCelebration()
                    }
            }
        }
        .padding(.top, Theme.s)
        .animation(Theme.spring, value: model.celebration)
    }
}
