import KartCore
import SwiftUI

/// A tiny top-down store map: aisles, the next stop filled in brand, and a dot for "you are here".
struct StoreMapView: View {
    let layout: StoreLayout
    let highlight: String?
    let here: String?

    var body: some View {
        Canvas { context, size in
            let sx = size.width / CGFloat(max(layout.store.width, 1))
            let sy = size.height / CGFloat(max(layout.store.height, 1))
            func rect(_ s: KartCore.Section) -> CGRect {
                CGRect(x: CGFloat(s.x) * sx, y: CGFloat(s.y) * sy, width: max(CGFloat(s.w) * sx, 6), height: CGFloat(s.h) * sy)
            }
            for section in layout.sections {
                let shape = Path(roundedRect: rect(section), cornerRadius: 3)
                if section.id == highlight {
                    context.fill(shape, with: .color(Theme.brand))
                } else {
                    context.fill(shape, with: .color(Theme.canvas))
                    context.stroke(shape, with: .color(Theme.hairline), lineWidth: 1.5)
                }
            }
            let start: CGPoint = if let here, let s = layout.sections.first(where: { $0.id == here }) {
                CGPoint(x: rect(s).midX, y: rect(s).maxY + sy * 0.6)
            } else {
                CGPoint(x: CGFloat(layout.entrance.x) * sx + 6, y: CGFloat(layout.entrance.y) * sy)
            }
            if let highlight, let target = layout.sections.first(where: { $0.id == highlight }) {
                let end = CGPoint(x: rect(target).midX, y: rect(target).maxY + sy * 0.6)
                var route = Path()
                route.move(to: start)
                route.addLine(to: CGPoint(x: end.x, y: start.y))
                route.addLine(to: end)
                context.stroke(route, with: .color(Theme.brand), style: StrokeStyle(lineWidth: 2.5, lineCap: .round, dash: [5, 5]))
            }
            let dot = CGRect(x: start.x - 7, y: start.y - 7, width: 14, height: 14)
            context.fill(Path(ellipseIn: dot.insetBy(dx: -3, dy: -3)), with: .color(.white))
            context.fill(Path(ellipseIn: dot), with: .color(Theme.ink))
        }
        .accessibilityHidden(true)
    }
}
