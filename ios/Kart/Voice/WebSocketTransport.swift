import Foundation
import KartCore

/// `LineTransport` over URLSessionWebSocketTask, with a ping every 60 s (Line closes idle sockets after 180 s).
@MainActor final class WebSocketTransport: LineTransport {
    private var task: URLSessionWebSocketTask?
    private var pinger: Task<Void, Never>?

    func connect(to url: URL) -> AsyncThrowingStream<String, Error> {
        close()
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        pinger = Task { [weak task] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(60))
                task?.sendPing { _ in }
            }
        }
        return AsyncThrowingStream { continuation in
            let reader = Task {
                do {
                    while !Task.isCancelled {
                        switch try await task.receive() {
                        case .string(let text): continuation.yield(text)
                        case .data(let data): continuation.yield(String(decoding: data, as: UTF8.self))
                        @unknown default: break
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in reader.cancel() }
        }
    }

    func send(_ text: String) async throws {
        try await task?.send(.string(text))
    }

    func close() {
        pinger?.cancel()
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }
}
