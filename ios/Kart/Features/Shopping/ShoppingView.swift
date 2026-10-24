import KartCore
import SwiftUI

/// Shopping: Kart on the left (40%), the trip on the right (60%). Task 11 fills the trip panel.
struct ShoppingView: View {
    let model: AppModel
    let namespace: Namespace.ID

    var body: some View {
        GeometryReader { geometry in
            HStack(spacing: 0) {
                KartPanel(model: model, namespace: namespace)
                    .frame(width: geometry.size.width * 0.4)
                Color.clear
            }
        }
        .padding(Theme.xxl)
    }
}
