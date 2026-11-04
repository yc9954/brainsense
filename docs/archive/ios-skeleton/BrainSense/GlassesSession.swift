import AVFoundation
import Foundation
import MWDATCore
import MWDATCamera
import MWDATSpeech

/// Owns the DAT connection, the camera stream, on-device ASR, and the speak-back path.
/// API names follow the 1.0.1 samples (CameraAccess / BirdSpotter); adjust to the exact SDK signatures when compiling.
@MainActor
final class GlassesSession: ObservableObject {
    @Published var status = "disconnected"
    @Published var lastReply = ""
    @Published var lastItemId = ""

    private let recorder = ClipRecorder(fps: 15)
    private let tts = AVSpeechSynthesizer()
    private var stream: CameraStreamSession?

    func connect() async {
        do {
            try await Wearables.shared.startRegistration()          // pairs with the Meta AI app (or MockDeviceKit)
            status = "registered"
            let session = try await CameraStreamSession(config: .init(resolution: .medium, frameRate: 15))
            session.onFrame = { [weak self] pixelBuffer, time in self?.recorder.push(pixelBuffer, at: time) }
            try await session.start()
            stream = session
            status = "streaming"
            try await startListening()
        } catch { status = "error: \(error.localizedDescription)" }
    }

    private func startListening() async throws {
        let recognizer = SpeechRecognitionSession()
        recognizer.onFinalResult = { [weak self] text in
            guard let self else { return }
            let lower = text.lowercased()
            if Config.triggerPhrases.contains(where: { lower.contains($0) }) {
                Task { await self.askAboutView(question: text) }
            } else if lower.contains("좋아") || lower.contains("별로") {
                Task { try? await BrainSenseClient.feedback(itemId: self.lastItemId, liked: lower.contains("좋아")) }
            }
        }
        try await recognizer.start()
    }

    func askAboutView(question: String) async {
        do {
            status = "encoding"
            let clip = try await recorder.exportClip()
            let itemId = "live-\(Int(Date().timeIntervalSince1970))"
            status = "brain…"
            _ = try await BrainSenseClient.analyze(clip: clip, itemId: itemId)
            status = "thinking…"
            let reply = try await BrainSenseClient.ask(itemId: itemId, question: question)
            lastItemId = itemId; lastReply = reply.text
            speak(reply.text)
            status = "streaming"
        } catch { status = "error: \(error.localizedDescription)" }
    }

    private func speak(_ text: String) {
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: [.allowBluetoothA2DP])
        let u = AVSpeechUtterance(string: text)
        u.voice = AVSpeechSynthesisVoice(language: "ko-KR")
        u.rate = 0.5
        tts.speak(u)   // routed to the glasses over A2DP
    }
}
