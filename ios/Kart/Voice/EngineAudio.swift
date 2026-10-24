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
        input.installTap(onBus: 0, bufferSize: chunk, format: micFormat) { [weak self] buffer, _ in
            guard let pcm = self?.convert(buffer) else { return }
            Task { @MainActor in self?.onMicChunk?(pcm) }
        }
        try engine.start()
        player.play()
    }

    func stop() {
        engine.inputNode.removeTap(onBus: 0)
        player.stop()
        engine.stop()
        queued = 0
    }

    func play(_ pcm: Data) {
        guard let buffer = floatBuffer(from: pcm) else { return }
        queued += 1
        player.scheduleBuffer(buffer) { [weak self] in
            Task { @MainActor in
                guard let self else { return }
                self.queued -= 1
                if self.queued <= 0 { self.queued = 0; self.onPlaybackIdle?() }
            }
        }
        if !player.isPlaying { player.play() }
    }

    func flush() {
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
