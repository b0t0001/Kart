import KartCore
import SwiftUI

/// Replays a logged trip for a screen recording (`-KartReplay <dir>/replay.json`, `-KartReplayAt <epoch seconds>` for
/// t = 0). It runs the mock backend with the hosted catalog and the member's real profile. Kart's and the shopper's
/// captions show verbatim at their logged times, and the camera's adds and removes land when they did. The shopper's
/// taps go through the same views. tools/replay/build_replay.py builds the file from the hosted logs. The result is a
/// reconstruction, not a recording of the original screen.
struct ReplayFile: Decodable {
    struct Item: Decodable {
        var productId: String
        var reason: String
        var qty: Int
        var basis: String?
    }

    struct Event: Decodable {
        /// Seconds from t = 0 (the video's first frame); negative before it.
        var t: Double
        /// caption, plan, unplan, vision, prompt, unprompt, accept_deal, checkout, sign_in, digit, confirm_member,
        /// pay, tap_reader.
        var action: String
        var role: String?
        var text: String?
        var value: String?
        var items: [Item]?
        var type: String?
        var productId: String?
        var confidence: Double?
        var label: String?
        var count: Int?
    }

    var label: String
    /// Next to replay.json, in data/store.json's shape.
    var catalog: String
    /// Next to replay.json: the hosted `member_profile` answer the sign-in loads.
    var memberProfile: String?
    var features: [String: Bool]
    var events: [Event]

    static func fromLaunch(_ defaults: UserDefaults = .standard) -> (file: ReplayFile, folder: URL)? {
        guard let path = defaults.string(forKey: "KartReplay") else { return nil }
        let url = URL(fileURLWithPath: path)
        guard let data = try? Data(contentsOf: url),
              let file = try? KartJSON.decoder().decode(ReplayFile.self, from: data) else { return nil }
        return (file, url.deletingLastPathComponent())
    }
}

/// The shopper's taps during a replay, for the views that own them (the sign-in sheet, Pay, the reader).
@MainActor @Observable final class ReplayDirector {
    var signInOpen = false
    var digits = ""
    var confirms = 0
    var pays = 0
    var readerTaps = 0
}

private struct ReplayDirectorKey: EnvironmentKey {
    static let defaultValue: ReplayDirector? = nil
}

extension EnvironmentValues {
    /// Set only while replaying a logged trip; nil otherwise.
    var replayDirector: ReplayDirector? {
        get { self[ReplayDirectorKey.self] }
        set { self[ReplayDirectorKey.self] = newValue }
    }
}

/// Kart's voice during a replay: silent, with the avatar's states taken from the captions' timing. Kart speaks from
/// just before its caption for as long as the words take; the shopper speaks up to a second before theirs, then Kart
/// thinks until it answers.
@MainActor @Observable final class ReplayVoiceSession: VoiceSession {
    struct Window {
        var from: Date
        var to: Date
        var state: VoiceState
    }

    private(set) var state: VoiceState = .idle
    private(set) var outputLevel: Double = 0
    let isMuted = false
    var holdToTalk = false
    let isHeld = false
    private(set) var agentPrompt: AgentPrompt?
    /// Never quiet: the logged trip decides when Kart talks, not the pause timer.
    var lastActiveAt: Date? { .now }

    @ObservationIgnored private var windows: [Window] = []
    @ObservationIgnored private var ticker: Task<Void, Never>?

    func plan(_ windows: [Window]) { self.windows = windows }
    func show(_ prompt: AgentPrompt?) { agentPrompt = prompt }

    func start(cartId: String, tripId: UUID) async {
        state = .connecting
        ticker?.cancel()
        ticker = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                self?.tick(.now)
                try? await Task.sleep(for: .milliseconds(33))
            }
        }
    }

    func stop() {
        ticker?.cancel()
        state = .idle
        outputLevel = 0
    }

    private func tick(_ now: Date) {
        let covering = windows.filter { $0.from <= now && now < $0.to }.map(\.state)
        let next: VoiceState = [.agentSpeaking, .userSpeaking, .thinking, .connecting].first(where: covering.contains) ?? .listening
        if next != state { state = next }
        if next == .agentSpeaking {
            let t = now.timeIntervalSinceReferenceDate
            outputLevel = 0.2 + 0.6 * abs(sin(t * 10.3)) * (0.65 + 0.35 * sin(t * 3.1))
        } else if outputLevel != 0 {
            outputLevel = 0
        }
    }

    func setMuted(_ muted: Bool) {}
    func setHeld(_ held: Bool) {}
    func send(_ event: VoiceEvent) {}
    func clearAgentPrompt() { agentPrompt = nil }
    func pause() {}
    func resume() async {}
}

/// Plays a `ReplayFile` against the mock backend and the app model, each event at its logged moment.
@MainActor final class ReplayDriver {
    let file: ReplayFile
    let folder: URL
    let director = ReplayDirector()
    let voice = ReplayVoiceSession()

    init(file: ReplayFile, folder: URL) {
        self.file = file
        self.folder = folder
    }

    var catalog: Catalog? { try? Catalog.load(from: folder.appending(path: file.catalog)) }

    func run(model: AppModel, backend: MockKartBackend) async {
        for (feature, on) in file.features { try? await backend.setFeature(feature, on: on) }
        if let name = file.memberProfile, let data = try? Data(contentsOf: folder.appending(path: name)),
           let profile = try? KartJSON.decoder().decode(MemberProfile.self, from: data) {
            backend.presetProfiles[profile.member.memberId] = profile
        }
        let events = file.events.sorted { $0.t < $1.t }
        let at = UserDefaults.standard.double(forKey: "KartReplayAt")
        let zero = at > 0 ? Date(timeIntervalSince1970: at) : Date.now.addingTimeInterval(2 - (events.first?.t ?? 0))
        voice.plan(Self.windows(events, zero: zero))
        for event in events {
            let wait = zero.addingTimeInterval(event.t).timeIntervalSinceNow
            if wait > 0 { try? await Task.sleep(for: .seconds(wait)) }
            await apply(event, model: model, backend: backend)
        }
    }

    private func apply(_ event: ReplayFile.Event, model: AppModel, backend: MockKartBackend) async {
        switch event.action {
        case "sign_in": director.signInOpen = true
        case "digit": director.digits += event.value ?? ""
        case "confirm_member": director.confirms += 1
        case "caption":
            try? await backend.appendTranscript(event.role == "user" ? .user : .agent, event.text ?? "")
        case "plan":
            let items = (event.items ?? []).map {
                PlanItem(productId: $0.productId, reason: $0.reason, qty: $0.qty, done: false, basis: $0.basis)
            }
            try? await backend.setPlan(items)
        case "unplan":
            if let id = event.productId { try? await backend.removeFromPlan(id) }
        case "vision":
            await backend.simulateVision(event.type == "removed" ? .removed : .added, productId: event.productId,
                                         confidence: event.confidence ?? 0.9, label: event.label ?? "")
        case "prompt": voice.show(.dealDigest(count: event.count ?? 1))
        case "unprompt": voice.show(nil)
        case "accept_deal":
            if let card = model.visibleCard, case .deal = card.kind { await model.respond(to: card, with: .yes) }
        case "checkout": try? await backend.setStatus(.checkout)      // the agent's start_checkout
        case "pay": director.pays += 1
        case "tap_reader": director.readerTaps += 1
        default: break
        }
        model.noteActivity()
    }

    /// The avatar's states from the captions: Kart speaks ~0.35 s before its caption for its words at ~2.8 a second;
    /// the shopper finishes ~0.9 s before theirs (the caption waits for Kart's first word), at ~2.6 words a second.
    static func windows(_ events: [ReplayFile.Event], zero: Date) -> [ReplayVoiceSession.Window] {
        let captions = events.filter { $0.action == "caption" }
        var windows: [ReplayVoiceSession.Window] = []
        if let confirm = events.first(where: { $0.action == "confirm_member" }),
           let greeting = captions.first(where: { $0.role == "agent" }) {
            windows.append(.init(from: zero.addingTimeInterval(confirm.t), to: zero.addingTimeInterval(greeting.t - 0.5),
                                 state: .connecting))
        }
        for (index, caption) in captions.enumerated() {
            let words = Double((caption.text ?? "").split(separator: " ").count)
            if caption.role == "user" {
                let end = caption.t - 0.9
                windows.append(.init(from: zero.addingTimeInterval(end - max(0.8, words / 2.6)), to: zero.addingTimeInterval(end),
                                     state: .userSpeaking))
                let answer = captions[(index + 1)...].first { $0.role == "agent" }.map { $0.t - 0.35 } ?? end + 1.5
                windows.append(.init(from: zero.addingTimeInterval(end), to: zero.addingTimeInterval(min(answer, end + 3)),
                                     state: .thinking))
            } else {
                let start = caption.t - 0.35
                windows.append(.init(from: zero.addingTimeInterval(start), to: zero.addingTimeInterval(start + max(1.2, words / 2.8)),
                                     state: .agentSpeaking))
            }
        }
        return windows
    }
}
