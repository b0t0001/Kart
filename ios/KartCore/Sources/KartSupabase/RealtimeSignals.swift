import Foundation

/// Supabase Realtime as change *signals*: one Phoenix channel per watched table, and every
/// `postgres_changes` message (or a (re)subscription) yields `()` so the caller refetches over REST.
/// Same handshake as `backend/e2e/realtime.py`.
public actor RealtimeSignals {
    public enum Event: Equatable, Sendable {
        case subscribed(topic: String)
        case change(topic: String)
        case joinError(topic: String, reason: String)
        case other
    }

    private struct Watch {
        let table: String
        let filter: String?
        let continuation: AsyncStream<Void>.Continuation
    }

    private let socketURL: URL
    private let anonKey: String
    private let session: URLSession
    private var watches: [String: Watch] = [:]
    private var joined: Set<String> = []
    private var runner: Task<Void, Never>?
    private var statusContinuation: AsyncStream<Bool>.Continuation?
    private var ref = 0

    public init(url: URL, anonKey: String, session: URLSession = .shared) {
        var components = URLComponents(url: url.appending(path: "realtime/v1/websocket"), resolvingAgainstBaseURL: false)!
        components.scheme = url.scheme == "https" ? "wss" : "ws"
        components.queryItems = [URLQueryItem(name: "apikey", value: anonKey), URLQueryItem(name: "vsn", value: "1.0.0")]
        self.socketURL = components.url!
        self.anonKey = anonKey
        self.session = session
    }

    /// Signals for one table (and optional PostgREST-style filter, e.g. `cart_id=eq.7`). Register before `start()`.
    public func watch(table: String, filter: String? = nil) -> AsyncStream<Void> {
        let topic = Self.topic(table: table, filter: filter)
        let (stream, continuation) = AsyncStream<Void>.makeStream(bufferingPolicy: .bufferingNewest(1))
        watches[topic] = Watch(table: table, filter: filter, continuation: continuation)
        return stream
    }

    /// `true` once every channel is subscribed; `false` while connecting or after a drop.
    public func statusUpdates() -> AsyncStream<Bool> {
        let (stream, continuation) = AsyncStream<Bool>.makeStream(bufferingPolicy: .bufferingNewest(1))
        statusContinuation = continuation
        continuation.yield(false)
        return stream
    }

    public func start() {
        guard runner == nil else { return }
        runner = Task { await self.run() }
    }

    public func stop() {
        runner?.cancel()
        runner = nil
    }

    // MARK: Connection loop

    private func run() async {
        var attempt = 0
        while !Task.isCancelled {
            let task = session.webSocketTask(with: socketURL)
            task.resume()
            joined = []
            for (topic, watch) in watches {
                try? await task.send(.string(Self.joinMessage(topic: topic, table: watch.table, filter: watch.filter,
                                                              anonKey: anonKey, ref: nextRef())))
            }
            let heartbeat = Task { [weak task] in
                while !Task.isCancelled {
                    try? await Task.sleep(for: .seconds(25))
                    try? await task?.send(.string(Self.heartbeatMessage(ref: UUID().uuidString)))
                }
            }
            do {
                while !Task.isCancelled {
                    let message = try await task.receive()
                    let data: Data = switch message {
                    case .string(let text): Data(text.utf8)
                    case .data(let data): data
                    @unknown default: Data()
                    }
                    if handle(Self.classify(data)) { attempt = 0 }
                }
            } catch {}
            heartbeat.cancel()
            task.cancel(with: .goingAway, reason: nil)
            statusContinuation?.yield(false)
            attempt += 1
            try? await Task.sleep(for: .seconds(min(15, 1 << min(attempt - 1, 4))))
        }
    }

    /// Returns true when the whole set just became subscribed.
    private func handle(_ event: Event) -> Bool {
        switch event {
        case .subscribed(let topic):
            guard watches[topic] != nil else { return false }
            joined.insert(topic)
            watches[topic]?.continuation.yield()          // refetch on every (re)join
            if joined.count == watches.count {
                statusContinuation?.yield(true)
                return true
            }
        case .change(let topic):
            watches[topic]?.continuation.yield()
        case .joinError, .other:
            break
        }
        return false
    }

    private func nextRef() -> String {
        ref += 1
        return String(ref)
    }

    // MARK: Protocol (pure, tested)

    static func topic(table: String, filter: String?) -> String {
        let suffix = filter.map { "-" + $0.replacingOccurrences(of: "=", with: "-").replacingOccurrences(of: ".", with: "-") } ?? ""
        return "realtime:kart-\(table)\(suffix)"
    }

    static func joinMessage(topic: String, table: String, filter: String?, anonKey: String, ref: String) -> String {
        var change: [String: Any] = ["event": "*", "schema": "public", "table": table]
        if let filter { change["filter"] = filter }
        let payload: [String: Any] = [
            "config": ["broadcast": ["self": false], "presence": ["key": ""], "postgres_changes": [change]],
            "access_token": anonKey,
        ]
        return encode(["topic": topic, "event": "phx_join", "payload": payload, "ref": ref, "join_ref": ref])
    }

    static func heartbeatMessage(ref: String) -> String {
        encode(["topic": "phoenix", "event": "heartbeat", "payload": [String: Any](), "ref": ref])
    }

    static func classify(_ data: Data) -> Event {
        guard let message = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let topic = message["topic"] as? String, let event = message["event"] as? String else { return .other }
        let payload = message["payload"] as? [String: Any] ?? [:]
        switch event {
        case "system":
            let ok = payload["status"] as? String == "ok"
            let subscribed = (payload["message"] as? String)?.contains("Subscribed") == true
            if ok && subscribed { return .subscribed(topic: topic) }
            if payload["status"] as? String == "error" { return .joinError(topic: topic, reason: payload["message"] as? String ?? "error") }
            return .other
        case "phx_reply":
            if payload["status"] as? String == "error" {
                let reason = (payload["response"] as? [String: Any])?["reason"] as? String
                return .joinError(topic: topic, reason: reason ?? "error")
            }
            return .other
        case "postgres_changes":
            return .change(topic: topic)
        default:
            return .other
        }
    }

    private static func encode(_ object: [String: Any]) -> String {
        let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data()
        return String(decoding: data, as: UTF8.self)
    }
}
