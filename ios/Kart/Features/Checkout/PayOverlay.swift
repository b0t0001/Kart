import KartCore
import SwiftUI

/// Tap-to-pay (simulated): a card glides toward the contactless mark, then success or a retry.
struct PayOverlay: View {
    let state: PaymentState
    let onRetry: () -> Void

    @Environment(\.kartStill) private var still
    @State private var glide = false

    var body: some View {
        ZStack {
            if state != .idle {
                Color.black.opacity(0.28).ignoresSafeArea().transition(.opacity)
                VStack(spacing: Theme.xl) {
                    content
                }
                .padding(Theme.xxxl)
                .frame(width: 520)
                .background(Theme.surface, in: RoundedRectangle(cornerRadius: 32, style: .continuous))
                .transition(.scale(scale: 0.92).combined(with: .opacity))
            }
        }
        .animation(Theme.spring, value: state)
    }

    @ViewBuilder private var content: some View {
        switch state {
        case .processing:
            HStack(spacing: Theme.xxl) {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Theme.brandDeep)
                    .frame(width: 120, height: 76)
                    .overlay(alignment: .bottomLeading) {
                        Capsule().fill(.white.opacity(0.7)).frame(width: 44, height: 6).padding(12)
                    }
                    .offset(x: glide ? 36 : -12)
                    .animation(.easeInOut(duration: 0.9).repeatForever(autoreverses: true), value: glide)
                Image(systemName: "wave.3.right")
                    .font(.system(size: 56, weight: .semibold))
                    .foregroundStyle(Theme.brand)
                    .symbolEffect(.variableColor.iterative, isActive: !still)
            }
            .onAppear { glide = !still }
            VStack(spacing: Theme.s) {
                Text("Paying…").font(Theme.title).foregroundStyle(Theme.ink)
                Text("Hold your card near the cart").font(Theme.body).foregroundStyle(Theme.inkSecondary)
            }
        case .failed(let message):
            Image(systemName: "exclamationmark.circle.fill").font(.system(size: 56)).foregroundStyle(Theme.amber)
            Text(message).font(Theme.headline).foregroundStyle(Theme.amberInk).multilineTextAlignment(.center)
            Button(action: onRetry) { Text("Try again").frame(maxWidth: .infinity) }
                .buttonStyle(PrimaryButtonStyle())
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 72)).foregroundStyle(Theme.green)
                .symbolEffect(.bounce, value: state)
            Text("Paid").font(Theme.title).foregroundStyle(Theme.ink)
        case .idle:
            EmptyView()
        }
    }
}
