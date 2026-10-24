import Foundation
import Observation

/// What the `voice-token` function returns (contract P7).
public struct VoiceToken: Decodable, Sendable, Equatable {
    public var token: String
    public var expiresAt: Date?
    public var agentId: String
    public var wsUrl: URL
    public var cartesiaVersion: String

    public init(token: String, expiresAt: Date? = nil, agentId: String, wsUrl: URL, cartesiaVersion: String) {
        self.token = token
        self.expiresAt = expiresAt
        self.agentId = agentId
        self.wsUrl = wsUrl
        self.cartesiaVersion = cartesiaVersion
    }
}

public protocol VoiceTokenProviding: Sendable {
    func token(cartId: String) async throws -> VoiceToken
}

/// A text WebSocket (URLSessionWebSocketTask in the app, a fake in tests).
@MainActor public protocol LineTransport: AnyObject {
    func connect(to url: URL) -> AsyncThrowingStream<String, Error>
    func send(_ text: String) async throws
    func close()
}

/// Microphone in (16 kHz mono PCM16 chunks, echo-cancelled) and Kart's voice out.
@MainActor public protocol LineAudio: AnyObject {
    var onMicChunk: ((Data) -> Void)? { get set }
    var onPlaybackIdle: (() -> Void)? { get set }
    func start() throws
    func stop()
    func play(_ pcm: Data)
    func flush()
    func level(of pcm: Data) -> Double
}

public enum LineServerEvent: Equatable, Sendable {
    case ack(streamId: String)
    case media(Data)
    case clear
    case prompt(AgentPrompt?)
    case other
}

/// The Cartesia Line agent WebSocket protocol, and the iPad → agent `custom` event contract.
public enum LineCodec {
    public static let inputFormat = "pcm_16000"

    /// The agent's card messages (contract between agent/kart_agent/agent.py and the iPad).
    static func prompt(_ meta: [String: Any]) -> LineServerEvent {
        switch meta["type"] as? String {
        case "deal_digest": return .prompt(.dealDigest(count: meta["count"] as? Int ?? 1))
        case "digest_deal":
            guard let dealId = meta["deal_id"] as? String, let productId = meta["product_id"] as? String,
                  let text = meta["text"] as? String else { return .other }
            return .prompt(.digestDeal(dealId: dealId, productId: productId, text: text))
        case "digest_done": return .prompt(nil)
        case "show_memories": return .prompt(.showMemories)
        default: return .other
        }
    }

    public static func start(streamId: String) -> String {
        encode(["event": "start", "stream_id": streamId, "config": ["input_format": inputFormat]])
    }

    public static func media(streamId: String, pcm: Data) -> String {
        encode(["event": "media_input", "stream_id": streamId, "media": ["payload": pcm.base64EncodedString()]])
    }

    public static func custom(streamId: String, event: VoiceEvent) -> String {
        encode(["event": "custom", "stream_id": streamId, "metadata": metadata(event)])
    }

    /// The agent reads these in `kart_agent/agent.py` and `lines.py`.
    public static func metadata(_ event: VoiceEvent) -> [String: Any] {
        switch event {
        case .tripContext(let cartId, let tripId, let memberId):
            var meta: [String: Any] = ["type": "trip_context", "cart_id": cartId, "trip_id": tripId.uuidString.lowercased()]
            if let memberId { meta["member_id"] = memberId }
            return meta
        case .lull:
            return ["type": "lull"]
        case .memberForgotten:
            return ["type": "member_forgotten"]
        case .memberIdle:
            return ["type": "member_idle"]
        case .cartChanged(.added(let productId)):
            return ["type": "cart_changed", "change": "added", "product_id": productId]
        case .cartChanged(.removed(let productId)):
            return ["type": "cart_changed", "change": "removed", "product_id": productId]
        case .cartChanged(.priceDropped(let productId, let from, let to)):
            return ["type": "cart_changed", "change": "price_dropped", "product_id": productId,
                    "from_price": "\(from)", "to_price": "\(to)"]
        case .suggestion(let s):
            return ["type": "suggestion", "deal_id": s.dealId, "product_id": s.productId, "text": s.text]
        case .dealChanged(let d):
            return ["type": "deal_changed", "deal_id": d.id, "product_id": d.productId, "label": d.label]
        case .cardResponse(let cardId, let action):
            return ["type": "card_response", "card_id": cardId, "action": name(of: action)]
        case .uiAction(let action):
            return ["type": "ui_action", "action": action]
        case .reconnected(let unanswered):
            return ["type": "reconnected", "unanswered": unanswered]
        case .nudge(let nudge):
            var meta: [String: Any] = ["type": "nudge", "product_id": nudge.productId, "kind": nudge.kind.rawValue,
                                       "text": nudge.text, "have": nudge.have, "need": nudge.need]
            if let items = nudge.items {                       // the combined checkout nudge: every short item
                meta["items"] = items.map { item -> [String: Any] in
                    var line: [String: Any] = ["product_id": item.productId, "have": item.have, "need": item.need]
                    if let name = item.name { line["name"] = name }
                    if let aisle = item.aisle { line["aisle"] = aisle }
                    return line
                }
            }
            return meta
        }
    }

    public static func decode(_ text: String) -> LineServerEvent {
        guard let message = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any],
              let event = message["event"] as? String else { return .other }
        switch event {
        case "ack": return .ack(streamId: message["stream_id"] as? String ?? "")
        case "media_output":
            guard let payload = (message["media"] as? [String: Any])?["payload"] as? String,
                  let pcm = Data(base64Encoded: payload) else { return .other }
            return .media(pcm)
        case "clear": return .clear
        case "custom": return prompt(message["metadata"] as? [String: Any] ?? [:])
        default: return .other
        }
    }

    private static func name(of action: CardAction) -> String {
        switch action {
        case .yes: "yes"
        case .no: "no"
        case .somethingElse: "something_else"
        case .remove: "remove"
        case .addIt: "add_it"
        case .gotIt: "got_it"
        case .keepIt: "keep_it"
        case .notNow: "not_now"
        case .goGetIt: "go_get_it"
        case .skipIt: "skip_it"
        case .goGetThem: "go_get_them"
        case .skip: "skip"
        case .retry: "retry"
        case .choose(let productId): "choose:\(productId)"
        }
    }

    private static func encode(_ object: [String: Any]) -> String {
        String(decoding: (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data(), as: UTF8.self)
    }
}

/// Hands-free conversation with the hosted Line agent: mic up, Kart's voice down, `clear` for barge-in.
/// A call that never acks, or a socket that drops, is retried with backoff (1 s, 2 s, 4 s) before going offline.
@MainActor @Observable
public final class LineVoiceSession: VoiceSession {
    public private(set) var state: VoiceState = .idle
    public private(set) var outputLevel: Double = 0
    public private(set) var isMuted = false
    public var holdToTalk = false
    public private(set) var isHeld = false
    public private(set) var agentPrompt: AgentPrompt?
    public private(set) var lastActiveAt: Date?

    public func clearAgentPrompt() { agentPrompt = nil }

    /// How loud a mic chunk must be (0–1, `LineAudio.level`) to count as the shopper talking.
    public static let speechLevel = 0.15

    @ObservationIgnored private let tokens: any VoiceTokenProviding
    @ObservationIgnored private let transport: any LineTransport
    @ObservationIgnored private let audio: any LineAudio
    @ObservationIgnored private let ackTimeout: Duration
    @ObservationIgnored private let backoff: [Duration]
    @ObservationIgnored private var streamId: String?
    @ObservationIgnored private var acked = false
    @ObservationIgnored private var receiver: Task<Void, Never>?
    @ObservationIgnored private var ackWaiter: CheckedContinuation<Bool, Never>?
    @ObservationIgnored private var trip: (cartId: String, tripId: UUID)?
    /// Member memory beta: the member the iPad last named for a trip, so every new call's own trip_context
    /// (the first one, a reconnect, a wake from pause) still names them.
    @ObservationIgnored private var member: (tripId: UUID, memberId: String)?
    @ObservationIgnored private var reconnecting = false
    @ObservationIgnored private let wakeAfter: Duration
    @ObservationIgnored private var paused = false
    @ObservationIgnored private var loudSince: Date?             // paused: when the current stretch of talking began
    @ObservationIgnored private var lastSpeechAt: Date?
    @ObservationIgnored private var lastKartAudioAt: Date?
    @ObservationIgnored private var announce: Bool?              // after the next connect: reconnected(unanswered:)
    @ObservationIgnored private var pending: [VoiceEvent] = []   // said while there was no call: sent once there is

    public init(tokens: any VoiceTokenProviding, transport: any LineTransport, audio: any LineAudio,
                ackTimeout: Duration = .seconds(10), backoff: [Duration] = [.seconds(1), .seconds(2), .seconds(4)],
                wakeAfter: Duration = .milliseconds(300)) {
        self.wakeAfter = wakeAfter
        self.tokens = tokens
        self.transport = transport
        self.audio = audio
        self.ackTimeout = ackTimeout
        self.backoff = backoff
    }

    public func start(cartId: String, tripId: UUID) async {
        let carried = announce                                 // a retry after going offline still owes the question
        stop()
        announce = carried
        trip = (cartId, tripId)
        _ = await connectWithRetries()
    }

    public func stop() {
        trip = nil
        paused = false
        pending = []
        announce = nil
        disconnect()
        outputLevel = 0
        state = .idle
    }

    /// Closes the call (no Cartesia minutes) but keeps the mic running here, so talking wakes it.
    public func pause() {
        guard trip != nil, !paused, state == .listening else { return }
        paused = true
        loudSince = nil
        receiver?.cancel()
        receiver = nil
        streamId = nil                                         // the receiver's end is now a deliberate one
        transport.close()
        resumeAck(false)
        audio.flush()
        outputLevel = 0
        state = .paused
    }

    public func resume() async {
        await wake(spoke: false)
    }

    private func wake(spoke: Bool) async {
        guard paused, trip != nil else { return }
        paused = false
        announce = spoke
        _ = await connectWithRetries()
    }

    public func setHeld(_ held: Bool) {
        isHeld = held
    }

    public func setMuted(_ muted: Bool) {
        isMuted = muted
    }

    public func send(_ event: VoiceEvent) {
        if case .tripContext(_, let tripId, let memberId) = event { member = memberId.map { (tripId, $0) } }
        if case .tripContext = event {} else { lastActiveAt = Date() }
        guard let streamId, state != .offline else {
            if case .tripContext = event { return }            // every new call sends its own
            if trip != nil, paused || state == .connecting {   // no call right now: keep it for the next one
                pending = Array((pending + [event]).suffix(8))
                if paused { Task { await wake(spoke: false) } }   // the cameras saw something: Kart has things to say
            }
            return
        }
        let text = LineCodec.custom(streamId: streamId, event: event)
        Task { try? await transport.send(text) }
    }

    // MARK: Connecting

    /// A fresh start tries at once; a reconnect after a drop waits before every attempt.
    private func connectWithRetries(afterDrop: Bool = false) async -> Bool {
        for attempt in (afterDrop ? 1 : 0)...backoff.count {
            if attempt > 0 {
                try? await Task.sleep(for: backoff[attempt - 1])
            }
            guard trip != nil else { return false }            // stopped while waiting
            if await connectOnce() { return true }
        }
        disconnect()
        state = .offline
        return false
    }

    private func connectOnce() async -> Bool {
        guard let trip else { return false }
        disconnect()
        state = .connecting
        guard let token = try? await tokens.token(cartId: trip.cartId) else { return false }
        var components = URLComponents(url: token.wsUrl, resolvingAgainstBaseURL: false)!
        components.queryItems = (components.queryItems ?? []) + [
            URLQueryItem(name: "cartesia_version", value: token.cartesiaVersion),
            URLQueryItem(name: "access_token", value: token.token),
        ]
        let messages = transport.connect(to: components.url!)
        let id = UUID().uuidString.lowercased()
        streamId = id
        acked = false
        receiver = Task { [weak self] in
            do {
                for try await text in messages { self?.handle(LineCodec.decode(text), on: id) }
            } catch {}
            self?.connectionEnded(id)
        }
        try? await transport.send(LineCodec.start(streamId: id))
        guard await waitForAck(), streamId == id else { return false }
        do {
            audio.onMicChunk = { [weak self] pcm in self?.sendMic(pcm) }
            audio.onPlaybackIdle = { [weak self] in self?.playbackIdle() }
            try audio.start()
        } catch {
            return false
        }
        state = .listening
        send(.tripContext(cartId: trip.cartId, tripId: trip.tripId,   // a fresh call knows nothing yet
                          memberId: member?.tripId == trip.tripId ? member?.memberId : nil))
        if let unanswered = announce {
            announce = nil
            send(.reconnected(unanswered: unanswered))
        }
        let queued = pending
        pending = []
        queued.forEach(send)
        return true
    }

    /// True once the server acks this stream; false after `ackTimeout` or if the socket ends first.
    private func waitForAck() async -> Bool {
        if acked { return true }                               // the ack beat us here
        let timeout = Task { [weak self, ackTimeout] in
            try? await Task.sleep(for: ackTimeout)
            self?.resumeAck(false)
        }
        defer { timeout.cancel() }
        return await withCheckedContinuation { ackWaiter = $0 }
    }

    private func disconnect() {
        receiver?.cancel()
        receiver = nil
        streamId = nil
        transport.close()
        audio.stop()
        resumeAck(false)
    }

    // MARK: Traffic

    private func sendMic(_ pcm: Data) {
        let talking = !isMuted && !(holdToTalk && !isHeld) && audio.level(of: pcm) >= Self.speechLevel
        if paused {                                            // nothing leaves the iPad; sustained talking wakes Kart
            guard talking else { loudSince = nil; return }
            let now = Date()
            let since = loudSince ?? now
            loudSince = since
            if now.timeIntervalSince(since) >= wakeAfter.seconds { loudSince = nil; Task { await wake(spoke: true) } }
            return
        }
        if talking { lastSpeechAt = Date(); lastActiveAt = lastSpeechAt }
        guard let streamId, !isMuted, state != .offline else { return }
        // Hold-to-talk: silence of the same length while not held, so store chatter never leaves the iPad, the stream
        // stays alive, and Line ends the shopper's turn on its own when they let go (Line has no end-of-turn message).
        let audio = holdToTalk && !isHeld ? Data(count: pcm.count) : pcm
        let text = LineCodec.media(streamId: streamId, pcm: audio)
        Task { try? await transport.send(text) }
    }

    private func handle(_ event: LineServerEvent, on id: String) {
        guard id == streamId else { return }                   // a late message from an old call
        switch event {
        case .ack:
            acked = true
            resumeAck(true)
        case .media(let pcm):
            lastKartAudioAt = Date()
            lastActiveAt = lastKartAudioAt
            audio.play(pcm)
            outputLevel = audio.level(of: pcm)
            state = .agentSpeaking
        case .prompt(let prompt):
            agentPrompt = prompt
        case .clear:
            audio.flush()
            playbackIdle()
        case .other:
            break
        }
    }

    private func playbackIdle() {
        outputLevel = 0
        if state == .agentSpeaking { state = .listening }
    }

    private func connectionEnded(_ id: String) {
        guard id == streamId else { return }                   // an old receiver finishing late, or a deliberate stop
        resumeAck(false)
        guard acked, !reconnecting, trip != nil else { return } // still connecting: connectOnce handles it
        reconnecting = true
        if let spoke = lastSpeechAt {                          // did the shopper's last words get an answer?
            announce = spoke > (lastKartAudioAt ?? .distantPast) && Date().timeIntervalSince(spoke) < 20
        } else {
            announce = false
        }
        audio.stop()
        outputLevel = 0
        state = .connecting
        Task { [weak self] in
            _ = await self?.connectWithRetries(afterDrop: true)
            self?.reconnecting = false
        }
    }

    private func resumeAck(_ value: Bool) {
        ackWaiter?.resume(returning: value)
        ackWaiter = nil
    }
}


private extension Duration {
    var seconds: Double { Double(components.seconds) + Double(components.attoseconds) / 1e18 }
}
