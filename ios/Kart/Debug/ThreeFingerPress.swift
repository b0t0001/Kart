import SwiftUI
import UIKit

/// A three-finger long press anywhere on the window, without blocking the app's own touches.
struct ThreeFingerPress: UIViewRepresentable {
    let action: () -> Void

    func makeUIView(context: Context) -> WindowGestureView {
        WindowGestureView(action: action)
    }

    func updateUIView(_ uiView: WindowGestureView, context: Context) {}

    final class WindowGestureView: UIView {
        private let action: () -> Void
        private var recognizer: UILongPressGestureRecognizer?

        init(action: @escaping () -> Void) {
            self.action = action
            super.init(frame: .zero)
            isUserInteractionEnabled = false
        }

        required init?(coder: NSCoder) { nil }

        override func didMoveToWindow() {
            super.didMoveToWindow()
            guard let window, recognizer == nil else { return }
            let press = UILongPressGestureRecognizer(target: self, action: #selector(fire(_:)))
            press.numberOfTouchesRequired = 3
            press.minimumPressDuration = 1.0
            press.cancelsTouchesInView = false
            window.addGestureRecognizer(press)
            recognizer = press
        }

        @objc private func fire(_ recognizer: UILongPressGestureRecognizer) {
            if recognizer.state == .began { action() }
        }
    }
}

private struct KartStillKey: EnvironmentKey {
    static let defaultValue = false
}

extension EnvironmentValues {
    /// `-KartStill YES`: pause ambient animation so UI tests can see the app go idle.
    var kartStill: Bool {
        get { self[KartStillKey.self] }
        set { self[KartStillKey.self] = newValue }
    }
}
