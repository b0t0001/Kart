import Foundation
import Network

/// Tells the app when the network comes back after being gone, so Kart's voice can retry on its own.
@MainActor final class NetworkWatch {
    private let monitor = NWPathMonitor()
    private var down = false

    func start(onRestored: @escaping @MainActor @Sendable () async -> Void) {
        monitor.pathUpdateHandler = { [weak self] path in
            let up = path.status == .satisfied
            Task { @MainActor in self?.update(up: up, onRestored: onRestored) }
        }
        monitor.start(queue: DispatchQueue(label: "kart.network"))
    }

    private func update(up: Bool, onRestored: @escaping @MainActor @Sendable () async -> Void) {
        if up, down { Task { await onRestored() } }
        down = !up
    }
}
