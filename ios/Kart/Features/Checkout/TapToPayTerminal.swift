import KartCore
import SwiftUI

/// Demo checkout terminal: the shopper holds their phone (Apple Wallet's "Hold Near Reader") to the iPad and taps the
/// reader. Nothing is charged: the cart's usual simulated payment runs once the tap is "read".
struct TapToPayTerminal: View {
    let total: Decimal
    let onPaid: () async -> Void
    let onCancel: () -> Void

    private enum Phase { case ready, reading, approved }
    @State private var phase: Phase = .ready
    @State private var wave = false

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            VStack(spacing: Theme.xxl) {
                VStack(spacing: Theme.s) {
                    Text("Total").font(Theme.headline).foregroundStyle(Theme.inkSecondary)
                    Text(Money.format(total)).font(Theme.display).monospacedDigit().foregroundStyle(Theme.ink)
                }
                reader
                VStack(spacing: Theme.s) {
                    Text(title).font(Theme.title).foregroundStyle(phase == .approved ? Theme.green : Theme.ink)
                        .contentTransition(.opacity)
                    Text(subtitle).font(Theme.body).foregroundStyle(Theme.inkSecondary)
                }
                .multilineTextAlignment(.center)
                .animation(Theme.spring, value: phase)
                if phase == .ready {
                    Button("Cancel", action: onCancel)
                        .buttonStyle(SecondaryButtonStyle())
                        .frame(maxWidth: 320)
                        .accessibilityIdentifier("tap.cancel")
                }
            }
            .padding(Theme.xxl)
        }
        .onAppear { wave = true }
    }

    private var title: String {
        switch phase {
        case .ready: "Hold your phone near the iPad"
        case .reading: "Reading…"
        case .approved: "Approved"
        }
    }

    private var subtitle: String {
        switch phase {
        case .ready: "Then tap the reader"
        case .reading: "Keep it there for a moment"
        case .approved: "Thanks for shopping with Kart"
        }
    }

    /// The contactless spot: rings that pulse while waiting, a check once approved.
    private var reader: some View {
        Button(action: read) {
            ZStack {
                ForEach(0..<3) { ring in
                    Circle()
                        .stroke(Theme.brand.opacity(0.35), lineWidth: 3)
                        .frame(width: 180, height: 180)
                        .scaleEffect(wave && phase == .ready ? 1.0 + CGFloat(ring + 1) * 0.22 : 1)
                        .opacity(wave && phase == .ready ? 0 : 0.8)
                        .animation(.easeOut(duration: 1.6).repeatForever(autoreverses: false).delay(Double(ring) * 0.4),
                                   value: wave)
                }
                Circle()
                    .fill(phase == .approved ? Theme.green : Theme.brand)
                    .frame(width: 180, height: 180)
                Image(systemName: phase == .approved ? "checkmark" : "wave.3.right")
                    .font(.system(size: 72, weight: .semibold))
                    .foregroundStyle(.white)
                    .symbolEffect(.variableColor.iterative, isActive: phase == .reading)
                    .contentTransition(.symbolEffect(.replace))
            }
            .frame(width: 300, height: 300)
            .contentShape(Circle())
        }
        .buttonStyle(.plain)
        .disabled(phase != .ready)
        .accessibilityLabel("Contactless reader")
        .accessibilityIdentifier("tap.reader")
    }

    private func read() {
        withAnimation(Theme.spring) { phase = .reading }
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(900))
            withAnimation(Theme.spring) { phase = .approved }
            try? await Task.sleep(for: .milliseconds(900))
            await onPaid()
        }
    }
}
