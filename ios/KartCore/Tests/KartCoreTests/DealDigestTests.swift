import Foundation
import Testing
@testable import KartCore

/// Deals: Kart asks first, then reads them one at a time; the agent tells the iPad which card to show.

@Test func agentMessagesDecodeIntoPrompts() {
    #expect(LineCodec.decode(#"{"event":"custom","metadata":{"type":"deal_digest","count":2}}"#) == .prompt(.dealDigest(count: 2)))
    let deal = #"{"event":"custom","metadata":{"type":"digest_deal","deal_id":"d-parm-3off","product_id":"kirkland-parmesan","#
        + #""text":"Parmesan is $3 off in Aisle 4. Want it?","index":1,"count":2}}"#
    #expect(LineCodec.decode(deal) == .prompt(.digestDeal(dealId: "d-parm-3off", productId: "kirkland-parmesan",
                                                          text: "Parmesan is $3 off in Aisle 4. Want it?")))
    #expect(LineCodec.decode(#"{"event":"custom","metadata":{"type":"digest_done"}}"#) == .prompt(nil))
    #expect(LineCodec.decode(#"{"event":"custom","metadata":{"type":"something_new"}}"#) == .other)
}

@MainActor @Test func theVoiceSessionKeepsKartsCurrentPrompt() async throws {
    let transport = FakeTransport(), audio = FakeAudio()
    let voice = LineVoiceSession(tokens: FakeTokens(), transport: transport, audio: audio)
    let starting = Task { await voice.start(cartId: "7", tripId: UUID()) }
    await settle()
    let streamId = try #require(transport.events("start").first?["stream_id"] as? String)
    transport.receive(#"{"event":"ack","stream_id":"\#(streamId)","config":{}}"#)
    await starting.value
    transport.receive(#"{"event":"custom","stream_id":"\#(streamId)","metadata":{"type":"deal_digest","count":1}}"#)
    await settle()
    #expect(voice.agentPrompt == .dealDigest(count: 1))
    voice.clearAgentPrompt()
    #expect(voice.agentPrompt == nil)
}

@MainActor @Test func kartsPromptShowsAsACardAndATapGoesBackToKart() async throws {
    let t = try make(); await t.model.startTrip()
    t.voice.agentPrompt = .dealDigest(count: 2)
    let ask = try #require(t.model.visibleCard)
    #expect(ask.id == "digest" && ask.title == "2 deals go with your list. Want to hear them?" && ask.actions == [.yes, .notNow])
    await t.model.respond(to: ask, with: .yes)
    #expect(t.voice.sent.last == .cardResponse(cardId: "digest", action: .yes) && t.voice.agentPrompt == nil)
    t.voice.agentPrompt = .digestDeal(dealId: "d-parm-3off", productId: "kirkland-parmesan", text: "Parmesan is $3 off in Aisle 4. Want it?")
    let deal = try #require(t.model.visibleCard)
    #expect(deal.id == "digest-deal-d-parm-3off" && deal.title == "Parmesan is $3 off in Aisle 4. Want it?" && deal.actions == [.yes, .no])
    #expect(t.backend.cart.plan.isEmpty)                         // Kart adds it on "yes"; the iPad doesn't add it twice
}
