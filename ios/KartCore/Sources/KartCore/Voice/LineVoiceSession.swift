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
    case other
}

/// The Cartesia Line agent WebSocket protocol, and the iPad → agent `custom` event contract.
public enum LineCodec {
    public static let inputFormat = "pcm_16000"

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
        case .tripContext(let cartId, let tripId):
            return ["type": "trip_context", "cart_id": cartId, "trip_id": tripId.uuidString.lowercased()]
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
        case .retry: "retry"
        case .choose(let productId): "choose:\(productId)"
        }
    }

    private static func encode(_ object: [String: Any]) -> String {
        String(decoding: (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])) ?? Data(), as: UTF8.self)
    }
}

/// Hands-free conversation with the hosted Line agent: mic up, Kart's voice down, `clear` for barge-in.
@MainActor @Observable
public final class LineVoiceSession: VoiceSession {
    public private(set) var state: VoiceState = .idle
    public private(set) var outputLevel: Double = 0
    public private(set) var isMuted = false

    @ObservationIgnored private let tokens: any VoiceTokenProviding
    @ObservationIgnored private let transport: any LineTransport
    @ObservationIgnored private let audio: any LineAudio
    @ObservationIgnored private var streamId: String?
    @ObservationIgnored private var receiver: Task<Void, Never>?
    @ObservationIgnored private var ackWaiter: CheckedContinuation<Bool, Never>?

    public init(tokens: any VoiceTokenProviding, transport: any LineTransport, audio: any LineAudio) {
        self.tokens = tokens
        self.transport = transport
        self.audio = audio
    }

    public func start(cartId: String, tripId: UUID) async {
        stop()
        state = .connecting
        guard let token = try? await tokens.token(cartId: cartId) else { state = .offline; return }
        var components = URLComponents(url: token.wsUrl, resolvingAgainstBaseURL: false)!
        components.queryItems = (components.queryItems ?? []) + [
            URLQueryItem(name: "cartesia_version", value: token.cartesiaVersion),
            URLQueryItem(name: "access_token", value: token.token),
        ]
        let messages = transport.connect(to: components.url!)
        let id = UUID().uuidString.lowercased()
        streamId = id
        receiver = Task { [weak self] in
            do {
                for try await text in messages { self?.handle(LineCodec.decode(text)) }
            } catch {}
            self?.connectionEnded()
        }
        try? await transport.send(LineCodec.start(streamId: id))
        let acked = await withCheckedContinuation { ackWaiter = $0 }
        guard acked else { return }
        do {
            audio.onMicChunk = { [weak self] pcm in self?.sendMic(pcm) }
            audio.onPlaybackIdle = { [weak self] in self?.playbackIdle() }
            try audio.start()
            state = .listening
        } catch {
            state = .offline
        }
    }

    public func stop() {
        receiver?.cancel()
        receiver = nil
        transport.close()
        audio.stop()
        streamId = nil
        resumeAck(false)
        outputLevel = 0
        state = .idle
    }

    public func setMuted(_ muted: Bool) {
        isMuted = muted
    }

    public func send(_ event: VoiceEvent) {
        guard let streamId, state != .offline else { return }
        let text = LineCodec.custom(streamId: streamId, event: event)
        Task { try? await transport.send(text) }
    }

    private func sendMic(_ pcm: Data) {
        guard let streamId, !isMuted, state != .offline else { return }
        let text = LineCodec.media(streamId: streamId, pcm: pcm)
        Task { try? await transport.send(text) }
    }

    private func handle(_ event: LineServerEvent) {
        switch event {
        case .ack:
            resumeAck(true)
        case .media(let pcm):
            audio.play(pcm)
            outputLevel = audio.level(of: pcm)
            state = .agentSpeaking
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

    private func connectionEnded() {
        guard streamId != nil else { return }      // a deliberate stop() already reset everything
        resumeAck(false)
        audio.stop()
        outputLevel = 0
        state = .offline
    }

    private func resumeAck(_ value: Bool) {
        ackWaiter?.resume(returning: value)
        ackWaiter = nil
    }
}
