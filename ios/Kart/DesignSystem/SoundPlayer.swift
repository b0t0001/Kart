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
        buffers = [
            .added: tones([(880, 0.07), (1320, 0.07)]),
            .removed: tones([(660, 0.07), (440, 0.07)]),
            .card: tones([(740, 0.12), (988, 0.12)]),
            .success: tones([(523, 0.10), (659, 0.10), (784, 0.16)]),
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

    /// Sine tones in sequence, each with an 8 ms attack and an exponential decay.
    private func tones(_ notes: [(frequency: Double, seconds: Double)]) -> AVAudioPCMBuffer? {
        let rate = format.sampleRate
        let total = AVAudioFrameCount(notes.reduce(0) { $0 + $1.seconds } * rate)
        guard let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: total), let data = buffer.floatChannelData?[0] else { return nil }
        buffer.frameLength = total
        var frame = 0
        for note in notes {
            let count = Int(note.seconds * rate)
            for i in 0..<count {
                let t = Double(i) / rate
                let attack = min(1, t / 0.008)
                let decay = exp(-t * 18)
                data[frame + i] = Float(0.25 * attack * decay * sin(2 * .pi * note.frequency * t))
            }
            frame += count
        }
        return buffer
    }
}
