import SwiftUI

/// A short burst of dots in Kart's colors. A new `trigger` plays it again.
struct ConfettiBurst: View {
    let trigger: UUID?
    var count: Int = 24
    var spread: CGFloat = 300
    var duration: TimeInterval = 1.5

    @State private var startedAt: Date?

    var body: some View {
        TimelineView(.animation(paused: startedAt == nil)) { timeline in
            Canvas { context, size in
                guard let startedAt else { return }
                let t = timeline.date.timeIntervalSince(startedAt)
                guard t < duration else { return }
                let center = CGPoint(x: size.width / 2, y: size.height / 2)
                let colors = [Theme.brand, Theme.amber, Theme.green]
                for i in 0..<count {
                    let angle = Double(i) / Double(count) * 2 * .pi + Double(i % 3) * 0.4
                    let speed = spread * (0.35 + 0.25 * Double((i * 7) % 5) / 4)
                    let x = center.x + cos(angle) * speed * t
                    let y = center.y + sin(angle) * speed * t + 260 * t * t
                    let radius = 5 + Double(i % 4)
                    let opacity = 1 - t / duration
                    context.opacity = opacity
                    context.fill(Path(ellipseIn: CGRect(x: x - radius, y: y - radius, width: radius * 2, height: radius * 2)),
                                 with: .color(colors[i % colors.count]))
                }
            }
        }
        .allowsHitTesting(false)
        .frame(width: spread * 1.2, height: spread * 1.2)
        .onChange(of: trigger) { _, newValue in
            guard newValue != nil else { return }
            startedAt = .now
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(duration))
                startedAt = nil
            }
        }
    }
}
