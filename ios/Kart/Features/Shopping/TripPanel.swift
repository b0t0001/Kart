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
            ForYouCard(model: model)                          // member memory beta; nothing for a guest
            HStack(alignment: .top, spacing: Theme.xl) {
                ListColumn(plan: cart.plan, items: cart.items, catalog: catalog,
                           onAdjust: cart.quantityNudgesOn ? { id, delta in Task { await model.adjust(id, by: delta) } } : nil)
                CartColumn(items: cart.items, unresolved: model.unresolvedCount, catalog: catalog)
            }
            .frame(maxHeight: .infinity)
            TotalFooter(model: model)
        }
        .overlay(alignment: .top) { CelebrationToast(model: model) }
        .animation(Theme.spring, value: model.forYouPicks.map(\.productId))
        .animation(Theme.spring, value: model.savedEvent?.id)
    }
}

/// Where to go next. No map and no "you're in…": the cart doesn't know where it is yet (no indoor location), so the card
/// only says where the shopper is headed. A tile on the left carries the state at a glance.
private struct NextStopCard: View {
    let model: AppModel

    var body: some View {
        let cart = model.backend.cart
        let stop = model.nextStop
        let done = stop == nil && !cart.plan.isEmpty
        HStack(spacing: Theme.xl) {
            Image(systemName: stop != nil ? "signpost.right.fill" : done ? "checkmark" : "basket.fill")
                .font(.system(size: 34, weight: .semibold))
                .foregroundStyle(done ? Theme.greenInk : Theme.brandDeep)
                .contentTransition(.symbolEffect(.replace))
                .frame(width: 80, height: 80)
                .background(done ? Theme.greenSoft : Theme.brandSoft,
                            in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            VStack(alignment: .leading, spacing: Theme.xs) {
                if let stop {
                    Text("Next stop").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    Text(stop.text).font(Theme.title).foregroundStyle(Theme.ink)
                        .lineLimit(2).minimumScaleFactor(0.8)
                        .contentTransition(.opacity)
                } else if done {
                    Text("All done").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    Text("Everything on your list is in the cart").font(Theme.title).foregroundStyle(Theme.greenInk)
                        .lineLimit(2).minimumScaleFactor(0.8)
                } else {
                    Text("Next stop").font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                    Text("Tell Kart what you're shopping for").font(Theme.title).foregroundStyle(Theme.ink)
                        .lineLimit(2).minimumScaleFactor(0.8)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(Theme.xl)
        .background(Theme.surface, in: RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .animation(Theme.spring, value: stop)
        .animation(Theme.spring, value: done)
    }
}

private struct ListColumn: View {
    let plan: [PlanItem]
    let items: [CartItem]
    let catalog: Catalog
    /// Quantity-nudge beta only: + / − on each line, a one-tap fix for a camera miscount.
    let onAdjust: ((String, Int) -> Void)?

    private func inCart(_ productId: String) -> Int {
        items.filter { $0.productId == productId }.reduce(0) { $0 + $1.qty }
    }

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
                    Text(PlanRow.title(line, name: line.name ?? catalog.product(line.productId)?.shortName ?? line.reason))
                        .font(Theme.body)
                        .foregroundStyle(line.done ? Theme.inkSecondary : Theme.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                    Spacer(minLength: Theme.s)
                    if line.inStock == false {
                        Text("Out of stock").font(Theme.caption).foregroundStyle(Theme.amberInk)
                    } else if !line.done {
                        if let deal = line.dealLabel { DealBadge(label: deal) }
                        if let progress = PlanRow.progress(line, inCart: inCart(line.productId)) {
                            // Partly in the cart: you're at that shelf, so "1 of 2" takes the aisle's place.
                            Text(progress).font(Theme.caption.weight(.medium)).foregroundStyle(Theme.greenInk)
                        } else if let aisle = line.aisle, onAdjust == nil {   // with +/−, Next stop carries the aisle
                            Text(aisle).font(Theme.caption).foregroundStyle(Theme.inkSecondary)
                        }
                    }
                    if let onAdjust, line.inStock != false {
                        CountStepper(count: inCart(line.productId), id: line.productId, onAdjust: onAdjust)
                    }
                }
                .frame(minHeight: Theme.minTap)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: plan)
    }
}

/// − / + for one list line (quantity-nudge beta): taps go through `apply_cart_event` as manual events. − is
/// disabled with nothing in the cart.
private struct CountStepper: View {
    let count: Int
    let id: String
    let onAdjust: (String, Int) -> Void

    var body: some View {
        HStack(spacing: Theme.xs) {
            button("minus", delta: -1).disabled(count == 0).opacity(count == 0 ? 0.35 : 1)
            button("plus", delta: 1)
        }
    }

    private func button(_ symbol: String, delta: Int) -> some View {
        Button { onAdjust(id, delta) } label: {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(Theme.brandDeep)
                .frame(width: 40, height: 40)
                .background(Theme.brandSoft, in: Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(delta > 0 ? "One more" : "One fewer")
        .accessibilityIdentifier("list.\(delta > 0 ? "plus" : "minus").\(id)")
    }
}

/// "$3 off", on a list row (a deal on something you planned) or a cart row (what you're paying).
private struct DealBadge: View {
    let label: String

    var body: some View {
        Text(label)
            .font(Theme.caption.weight(.medium)).foregroundStyle(Theme.greenInk)
            .lineLimit(1)
            .padding(.horizontal, Theme.m).padding(.vertical, Theme.xs)
            .background(Theme.greenSoft, in: Capsule())
            .fixedSize()                                   // never squeezed: the product name gives way first
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
