import Foundation
import Testing
@testable import KartCore

// MARK: Fakes

@MainActor final class FakeTransport: LineTransport {
    var sent: [[String: Any]] = []
    var connectedURL: URL?
    private var continuation: AsyncThrowingStream<String, Error>.Continuation?

    func connect(to url: URL) -> AsyncThrowingStream<String, Error> {
        connectedURL = url
        let (stream, continuation) = AsyncThrowingStream<String, Error>.makeStream()
        self.continuation = continuation
        return stream
    }
    func send(_ text: String) async throws {
        sent.append(try JSONSerialization.jsonObject(with: Data(text.utf8)) as! [String: Any])
    }
    func close() { continuation?.finish() }
    func receive(_ json: String) { continuation?.yield(json) }
    func drop() { continuation?.finish(throwing: URLError(.networkConnectionLost)) }
    func events(_ name: String) -> [[String: Any]] { sent.filter { $0["event"] as? String == name } }
}

@MainActor final class FakeAudio: LineAudio {
    var onMicChunk: ((Data) -> Void)?
    var onPlaybackIdle: (() -> Void)?
    var played: [Data] = []
    var flushes = 0
    var running = false
    func start() throws { running = true }
    func stop() { running = false }
    func play(_ pcm: Data) { played.append(pcm) }
    func flush() { flushes += 1 }
    func level(of pcm: Data) -> Double { 0.5 }
}

struct FakeTokens: VoiceTokenProviding {
    func token(cartId: String) async throws -> VoiceToken {
        VoiceToken(token: "tok", expiresAt: nil, agentId: "agent_1", wsUrl: URL(string: "wss://api.cartesia.ai/agents/stream/agent_1")!,
                   cartesiaVersion: "2026-08-14")
    }
}

@MainActor private func settle() async { for _ in 0..<5 { await Task.yield() } }

// MARK: Tests

@Test func codecEncodesStartMediaAndCustom() throws {
    let start = try #require(try JSONSerialization.jsonObject(with: Data(LineCodec.start(streamId: "s1").utf8)) as? [String: Any])
    #expect(start["event"] as? String == "start" && start["stream_id"] as? String == "s1")
    #expect((start["config"] as? [String: Any])?["input_format"] as? String == "pcm_16000")
    let media = try #require(try JSONSerialization.jsonObject(with: Data(LineCodec.media(streamId: "s1", pcm: Data([1, 2, 3])).utf8)) as? [String: Any])
    #expect((media["media"] as? [String: Any])?["payload"] as? String == "AQID")
    let custom = try #require(try JSONSerialization.jsonObject(with: Data(LineCodec.custom(streamId: "s1",
        event: .cartChanged(.priceDropped(productId: "kirkland-parmesan", from: Decimal(string: "12.99")!, to: Decimal(string: "9.99")!))).utf8)) as? [String: Any])
    let meta = try #require(custom["metadata"] as? [String: Any])
    #expect(meta["type"] as? String == "cart_changed" && meta["change"] as? String == "price_dropped" && meta["to_price"] as? String == "9.99")
}

@Test func codecDecodesServerEvents() {
    #expect(LineCodec.decode(#"{"event":"ack","stream_id":"s1","config":{}}"#) == .ack(streamId: "s1"))
    #expect(LineCodec.decode(#"{"event":"media_output","stream_id":"s1","media":{"payload":"AQID"}}"#) == .media(Data([1, 2, 3])))
    #expect(LineCodec.decode(#"{"event":"clear","stream_id":"s1"}"#) == .clear)
    #expect(LineCodec.decode("nope") == .other)
}

@Test func voiceEventsMapToTheAgentContract() {
    let s = Suggestion(productId: "kirkland-parmesan", dealId: "d-parm-3off", text: "Parmesan is $3 off in Aisle 4. Want it?")
    #expect(LineCodec.metadata(.suggestion(s))["text"] as? String == s.text)
    #expect(LineCodec.metadata(.tripContext(cartId: "7", tripId: UUID(uuidString: "6F9619FF-8B86-D011-B42D-00C04FC964FF")!))["trip_id"] as? String
            == "6f9619ff-8b86-d011-b42d-00c04fc964ff")
    #expect(LineCodec.metadata(.uiAction("checkout_tapped"))["action"] as? String == "checkout_tapped")
}

@MainActor @Test func startsStreamsAndPlaysAgentAudio() async throws {
    let transport = FakeTransport(), audio = FakeAudio()
    let voice = LineVoiceSession(tokens: FakeTokens(), transport: transport, audio: audio)
    let starting = Task { await voice.start(cartId: "7", tripId: UUID()) }
    await settle()
    #expect(voice.state == .connecting)
    #expect(transport.connectedURL?.absoluteString.contains("access_token=tok") == true)
    #expect(transport.connectedURL?.absoluteString.contains("cartesia_version=2026-08-14") == true)
    let streamId = try #require(transport.events("start").first?["stream_id"] as? String)
    transport.receive(#"{"event":"ack","stream_id":"\#(streamId)","config":{}}"#)
    await starting.value
    #expect(voice.state == .listening && audio.running)

    audio.onMicChunk?(Data([0, 0, 1, 0]))
    await settle()
    #expect(transport.events("media_input").count == 1)
    voice.setMuted(true)
    audio.onMicChunk?(Data([0, 0, 1, 0]))
    await settle()
    #expect(transport.events("media_input").count == 1)       // muted: nothing leaves the iPad

    transport.receive(#"{"event":"media_output","stream_id":"\#(streamId)","media":{"payload":"AQID"}}"#)
    await settle()
    #expect(voice.state == .agentSpeaking && audio.played == [Data([1, 2, 3])] && voice.outputLevel > 0)
    transport.receive(#"{"event":"clear","stream_id":"\#(streamId)"}"#)
    await settle()
    #expect(audio.flushes == 1 && voice.state == .listening)  // barge-in

    voice.send(.uiAction("checkout_tapped"))
    await settle()
    #expect(transport.events("custom").last.flatMap { $0["metadata"] as? [String: Any] }?["action"] as? String == "checkout_tapped")
}

@MainActor @Test func aDroppedSocketGoesOffline() async throws {
    let transport = FakeTransport(), audio = FakeAudio()
    let voice = LineVoiceSession(tokens: FakeTokens(), transport: transport, audio: audio)
    let starting = Task { await voice.start(cartId: "7", tripId: UUID()) }
    await settle()
    let streamId = try #require(transport.events("start").first?["stream_id"] as? String)
    transport.receive(#"{"event":"ack","stream_id":"\#(streamId)","config":{}}"#)
    await starting.value
    transport.drop()
    await settle()
    #expect(voice.state == .offline && !audio.running)
}
