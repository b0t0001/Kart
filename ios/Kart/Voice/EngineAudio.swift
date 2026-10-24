@preconcurrency import AVFoundation
import KartCore

/// Mic and speaker for the Line agent. Voice processing on the input node cancels Kart's own voice
/// (so it doesn't interrupt itself); the mic is converted to 16 kHz mono PCM16 in ~40 ms chunks.
/// Kart's voice is assumed to come back in the same format; `outputSampleRate` makes that easy to change
/// once it's verified on a real iPad (the Line docs don't say).
@MainActor final class EngineAudio: LineAudio {
    var onMicChunk: ((Data) -> Void)?
    var onPlaybackIdle: (() -> Void)?

    nonisolated static let sampleRate: Double = 16_000
    var outputSampleRate: Double = 16_000

    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var queued = 0
    private var played = 0
    private var configurationObserver: NSObjectProtocol?

    func start() throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .voiceChat, options: [.defaultToSpeaker, .allowBluetoothHFP])
        try session.setActive(true)
        let input = engine.inputNode
        try input.setVoiceProcessingEnabled(true)
        let micFormat = input.outputFormat(forBus: 0)
        let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: outputSampleRate, channels: 1, interleaved: false)!
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: playFormat)
        let chunk = AVAudioFrameCount(micFormat.sampleRate * 0.04)
        // @Sendable: AVAudio calls taps and completions on its own realtime queue; without it Swift 6 infers @MainActor
        // from this method and traps on the first mic buffer (seen on device: _swift_task_checkIsolated).
        input.installTap(onBus: 0, bufferSize: chunk, format: micFormat) { @Sendable [weak self] buffer, _ in
            guard let pcm = self?.convert(buffer) else { return }
            Task { @MainActor in self?.onMicChunk?(pcm) }
        }
        try engine.start()
        player.play()
        // iOS stops the engine when the audio setup changes (route, another engine, an interruption); restart it,
        // or Kart's voice is scheduled into a stopped engine and never heard.
        configurationObserver = NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            MainActor.assumeIsolated {
                guard let self else { return }
                self.log("configuration change: engine \(self.engine.isRunning), player \(self.player.isPlaying), queued \(self.queued)")
                self.restart(because: "configuration change")
            }
        }
        log("started: output \(session.currentRoute.outputs.map { $0.portType.rawValue }), volume \(session.outputVolume)")
    }

    private func restart(because reason: String) {
        guard !engine.isRunning else { return }
        // The player's timeline stopped with the engine but it still reports isPlaying, and play() on it then renders
        // nothing: on device the greeting queued up unheard until a flush reset it. Reset it here instead.
        player.stop()
        queued = 0
        do {
            try engine.start()
            player.play()
            log("restarted after \(reason)")
        } catch {
            log("restart after \(reason) failed: \(error)")
        }
    }

    private func log(_ message: String) { print("[KartAudio] \(message)") }

    func stop() {
        configurationObserver.map(NotificationCenter.default.removeObserver)
        configurationObserver = nil
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        queued = 0
    }

    func play(_ pcm: Data) {
        guard let buffer = floatBuffer(from: pcm) else { return }
        if !engine.isRunning { restart(because: "audio arrived while stopped") }
        played += 1
        if played == 1 || played % 100 == 0 {
            let session = AVAudioSession.sharedInstance()
            log("playing chunk \(played): engine \(engine.isRunning), player \(player.isPlaying), output \(session.currentRoute.outputs.map { $0.portType.rawValue }), volume \(session.outputVolume)")
        }
        queued += 1
        player.scheduleBuffer(buffer) { @Sendable [weak self] in
            Task { @MainActor in
                guard let self, self.queued > 0 else { return }   // a flush already zeroed it: one idle, not one per buffer
                self.queued -= 1
                if self.queued == 0 { self.onPlaybackIdle?() }
            }
        }
        if !player.isPlaying { player.play() }
    }

    func flush() {
        log("flush (Line cleared Kart's audio: the shopper or noise cut in): dropping \(queued) queued chunks")
        player.stop()
        queued = 0
        player.play()
    }

    /// RMS of PCM16 mono, scaled to roughly 0–1 for the mouth.
    func level(of pcm: Data) -> Double {
        let samples = pcm.withUnsafeBytes { Array($0.bindMemory(to: Int16.self)) }
        guard !samples.isEmpty else { return 0 }
        let rms = sqrt(samples.reduce(0.0) { $0 + pow(Double($1) / 32768, 2) } / Double(samples.count))
        return min(1, rms * 4)
    }

    nonisolated private func convert(_ buffer: AVAudioPCMBuffer) -> Data? {
        // Built per call: AVAudioConverter isn't Sendable, and the tap runs off the main actor.
        let wire = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: Self.sampleRate, channels: 1, interleaved: true)!
        guard let converter = AVAudioConverter(from: buffer.format, to: wire) else { return nil }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * Self.sampleRate / buffer.format.sampleRate) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: wire, frameCapacity: capacity) else { return nil }
        final class Once: @unchecked Sendable { var fed = false }
        let once = Once()
        nonisolated(unsafe) let source = buffer
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if once.fed { status.pointee = .noDataNow; return nil }
            once.fed = true
            status.pointee = .haveData
            return source
        }
        guard error == nil, let channel = out.int16ChannelData else { return nil }
        return Data(bytes: channel[0], count: Int(out.frameLength) * 2)
    }

    private func floatBuffer(from pcm: Data) -> AVAudioPCMBuffer? {
        let format = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: outputSampleRate, channels: 1, interleaved: false)!
        let count = pcm.count / 2
        guard count > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(count)),
              let channel = buffer.floatChannelData?[0] else { return nil }
        buffer.frameLength = AVAudioFrameCount(count)
        pcm.withUnsafeBytes { raw in
            let samples = raw.bindMemory(to: Int16.self)
            for i in 0..<count { channel[i] = Float(samples[i]) / 32768 }
        }
        return buffer
    }
}
