import Foundation
import Observation

/// Kart's voice with no network: the scripted brain plus on-device speech, one line at a time.
@MainActor @Observable
public final class MockVoiceSession: VoiceSession {
    public private(set) var state: VoiceState = .idle
    public private(set) var outputLevel: Double = 0
    public private(set) var isMuted = false

    /// Debug: simulate the voice connection dropping.
    public var forcedOffline = false {
        didSet { state = forcedOffline ? .offline : (started ? .listening : .idle) }
    }

    @ObservationIgnored private let brain: MockAgentBrain
    @ObservationIgnored private let backend: any KartBackend
    @ObservationIgnored private let speech: any SpeechOutput
    @ObservationIgnored private var started = false
    @ObservationIgnored private var tail: Task<Void, Never>?
    @ObservationIgnored private var levelTask: Task<Void, Never>?

    public init(brain: MockAgentBrain, backend: any KartBackend, speech: any SpeechOutput) {
        self.brain = brain
        self.backend = backend
        self.speech = speech
    }

    public func start(cartId: String, tripId: UUID) async {
        guard !forcedOffline else { state = .offline; return }
        started = true
        state = .connecting
        await speak(DemoScript.greeting)
    }

    public func stop() {
        started = false
        tail = nil
        levelTask?.cancel()
        outputLevel = 0
        state = forcedOffline ? .offline : .idle
    }

    public func setMuted(_ muted: Bool) {
        isMuted = muted
    }

    public func send(_ event: VoiceEvent) {
        guard started, !forcedOffline, let line = brain.react(to: event) else { return }
        Task { await speak(line) }
    }

    /// Debug panel and tests: the shopper said something.
    public func simulateUserSays(_ text: String) async {
        guard started, !isMuted, !forcedOffline else { return }
        try? await backend.appendTranscript(.user, text)
        state = .thinking
        let reply = await brain.respond(to: text)
        await speak(reply)
    }

    /// Queues the line behind anything already speaking and returns when it has been spoken.
    private func speak(_ line: String) async {
        let previous = tail
        let task = Task { @MainActor in
            await previous?.value
            await self.say(line)
        }
        tail = task
        await task.value
    }

    private func say(_ line: String) async {
        guard started, !forcedOffline else { return }
        try? await backend.appendTranscript(.agent, line)
        state = .agentSpeaking
        animateLevel()
        await speech.speak(line)
        levelTask?.cancel()
        outputLevel = 0
        if started { state = forcedOffline ? .offline : .listening }
    }

    private func animateLevel() {
        levelTask?.cancel()
        levelTask = Task { @MainActor [weak self] in
            let start = Date.now
            while !Task.isCancelled {
                let t = Date.now.timeIntervalSince(start)
                self?.outputLevel = 0.55 + 0.3 * sin(t * 12) * abs(sin(t * 3.1))
                try? await Task.sleep(for: .milliseconds(33))
            }
        }
    }
}
