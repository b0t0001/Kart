import AVFoundation
import KartCore

/// On-device text-to-speech for the offline demo voice. Cartesia replaces it in milestone 3.
@MainActor final class SystemSpeech: NSObject, SpeechOutput, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    private let voice: AVSpeechSynthesisVoice?
    private var continuation: CheckedContinuation<Void, Never>?

    override init() {
        voice = AVSpeechSynthesisVoice.speechVoices().first { $0.language == "en-US" && $0.quality == .premium }
            ?? AVSpeechSynthesisVoice(language: "en-US")
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ text: String) async {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = voice
        utterance.rate = 0.5
        await withCheckedContinuation { continuation in
            self.continuation?.resume()
            self.continuation = continuation
            synthesizer.speak(utterance)
        }
    }

    private func finish() {
        continuation?.resume()
        continuation = nil
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finish() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finish() }
    }
}
