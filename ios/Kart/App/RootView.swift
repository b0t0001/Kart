import KartCore
import SwiftUI

struct RootView: View {
    let model: AppModel
    @Namespace private var kart

    var body: some View {
        ZStack {
            Theme.canvas.ignoresSafeArea()
            switch model.screen {
            case .welcome:
                WelcomeView(model: model, namespace: kart)
                    .transition(.opacity)
            case .greeting:
                GreetingView(model: model, namespace: kart)
                    .transition(.opacity)
            case .shopping:
                ShoppingView(model: model, namespace: kart)
                    .transition(.opacity)
            case .checkout:
                CheckoutView(model: model)
                    .transition(.move(edge: .trailing).combined(with: .opacity))
            case .receipt:
                ReceiptView(model: model)
                    .transition(.opacity)
            }
        }
        .animation(Theme.spring, value: model.screen)
    }
}
