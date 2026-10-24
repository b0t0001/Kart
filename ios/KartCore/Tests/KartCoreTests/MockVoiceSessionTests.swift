import Foundation
import Testing
@testable import KartCore

@MainActor struct MockVoiceSessionTests {
    @Test func greetsThenListens() async throws {
        let b = MockKartBackend(catalog: try Fixtures.catalog()); try await b.startTrip()
        let speech = SilentSpeech(); let v = MockVoiceSession(brain: MockAgentBrain(backend: b), backend: b, speech: speech)
        await v.start(cartId: "7", tripId: try #require(b.cart.tripId))
        #expect(b.transcript.map(\.text) == [DemoScript.greeting] && speech.spoken == [DemoScript.greeting])
        #expect(v.state == .listening)
    }
    @Test func userLineFlowsToTranscriptAndPlan() async throws {
        let b = MockKartBackend(catalog: try Fixtures.catalog()); try await b.startTrip()
        let v = MockVoiceSession(brain: MockAgentBrain(backend: b), backend: b, speech: SilentSpeech())
        await v.start(cartId: "7", tripId: try #require(b.cart.tripId))
        await v.simulateUserSays(DemoScript.userLines[0])
        #expect(b.transcript.map(\.role) == [.agent, .user, .agent])
        #expect(b.cart.plan.count == 4)
    }
    @Test func mutedAndOfflineIgnoreSpeech() async throws {
        let b = MockKartBackend(catalog: try Fixtures.catalog()); try await b.startTrip()
        let v = MockVoiceSession(brain: MockAgentBrain(backend: b), backend: b, speech: SilentSpeech())
        await v.start(cartId: "7", tripId: try #require(b.cart.tripId))
        v.setMuted(true); await v.simulateUserSays("pasta"); #expect(b.transcript.count == 1)
        v.setMuted(false); v.forcedOffline = true; #expect(v.state == .offline)
        await v.simulateUserSays("pasta"); #expect(b.transcript.count == 1)
    }
}
