import AVFoundation
import KartCore

/// Short synthesized cues, so there are no audio assets to license.
@MainActor final class SoundPlayer: SoundPlaying {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
    private var buffers: [SoundCue: AVAudioPCMBuffer] = [:]

    init() {
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        // Small bells: each note rings over the next. Added rises ("bloop-ding"), removed falls back down softly,
        // a card is a gentle two-note "hey", paid is a little arpeggio.
        buffers = [
            .added: chime([(784, 0, 0.18), (1175, 0.07, 0.40)]),
            .removed: chime([(1175, 0, 0.14), (784, 0.07, 0.30)], level: 0.6),
            .card: chime([(659, 0, 0.20), (988, 0.10, 0.45)], level: 0.8),
            .success: chime([(523, 0, 0.25), (659, 0.08, 0.25), (784, 0.16, 0.30), (1047, 0.24, 0.70)]),
        ].compactMapValues { $0 }
    }

    func play(_ cue: SoundCue) {
        guard let buffer = buffers[cue] else { return }
        if !engine.isRunning {
            // Never downgrade the session while the Line voice owns it (.playAndRecord): .ambient would kill the mic.
            let session = AVAudioSession.sharedInstance()
            if session.category != .playAndRecord {
                try? session.setCategory(.ambient, options: .mixWithOthers)
            }
            try? engine.start()                      // also restarts after the voice engine reconfigured the session
        }
        guard engine.isRunning else { return }
        player.scheduleBuffer(buffer, at: nil, options: .interrupts)
        player.play()
    }

    /// Bell-like notes (a fundamental plus soft 2nd and 3rd partials), each with a 4 ms attack and an exponential
    /// ring: (frequency, start, ring seconds). Notes overlap, so it sounds like one little phrase, not beeps.
    private func chime(_ notes: [(frequency: Double, start: Double, ring: Double)], level: Double = 1) -> AVAudioPCMBuffer? {
        let rate = format.sampleRate
        let end = notes.map { $0.start + $0.ring }.max() ?? 0
        let total = AVAudioFrameCount(end * rate)
        guard total > 0, let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: total),
              let data = buffer.floatChannelData?[0] else { return nil }
        buffer.frameLength = total
        for i in 0..<Int(total) { data[i] = 0 }
        let partials: [(ratio: Double, gain: Double)] = [(1, 1), (2, 0.32), (3, 0.1)]
        for note in notes {
            let first = Int(note.start * rate)
            let count = min(Int(note.ring * rate), Int(total) - first)
            for i in 0..<max(0, count) {
                let t = Double(i) / rate
                let envelope = min(1, t / 0.004) * exp(-t * 4.5 / note.ring)
                let tone = partials.reduce(0) { $0 + $1.gain * sin(2 * .pi * note.frequency * $1.ratio * t) }
                data[first + i] += Float(0.16 * level * envelope * tone)
            }
        }
        return buffer
    }
}
