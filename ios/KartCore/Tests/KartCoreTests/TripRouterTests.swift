import Foundation
import Testing
@testable import KartCore

@Test func routerFollowsStatusAndFirstExchange() {
    var c = CartState.empty(cartId: "7")
    #expect(TripRouter.screen(cart: c, transcript: []) == .welcome)
    c.status = .shopping
    #expect(TripRouter.screen(cart: c, transcript: [line(.agent, "Hi, I'm Kart.")]) == .greeting)
    #expect(TripRouter.screen(cart: c, transcript: [line(.agent, "Hi"), line(.user, "pasta")]) == .shopping)
    c.status = .checkout; #expect(TripRouter.screen(cart: c, transcript: []) == .checkout)
    c.status = .paid;     #expect(TripRouter.screen(cart: c, transcript: []) == .receipt)
}

@Test func moodMapping() {
    #expect(AvatarMood(.userSpeaking) == .listening)
    #expect(AvatarMood(.agentSpeaking) == .speaking)
    #expect(AvatarMood(.offline) == .idle)
    #expect(AvatarMood(.thinking) == .thinking)
}
