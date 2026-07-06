import Foundation
import Speech
import AVFoundation

// Native speech-to-text for the app. WKWebView can't use the browser's speech
// API, so the web mic button hands off to this: it records with the mic,
// transcribes on device, and streams the text back into the web UI.
final class VoiceInput: NSObject {
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var lastText = ""
    private var finalized = false

    var onPartial: ((String) -> Void)?
    var onFinal: ((String) -> Void)?
    var onState: ((Bool) -> Void)?
    private(set) var listening = false

    func toggle() { listening ? stop() : start() }

    func start() {
        SFSpeechRecognizer.requestAuthorization { auth in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                DispatchQueue.main.async {
                    guard auth == .authorized, granted else { self.onState?(false); return }
                    self.begin()
                }
            }
        }
    }

    private func begin() {
        guard let recognizer, recognizer.isAvailable else { onState?(false); return }
        lastText = ""; finalized = false
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            let req = SFSpeechAudioBufferRecognitionRequest()
            req.shouldReportPartialResults = true
            request = req

            let input = engine.inputNode
            let format = input.outputFormat(forBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                req.append(buffer)
            }
            engine.prepare()
            try engine.start()
            listening = true; onState?(true)

            task = recognizer.recognitionTask(with: req) { [weak self] result, error in
                guard let self else { return }
                if let result {
                    self.lastText = result.bestTranscription.formattedString
                    self.onPartial?(self.lastText)
                    if result.isFinal { self.finish() }
                }
                if error != nil { self.finish() }
            }
        } catch {
            onState?(false); stop()
        }
    }

    private func finish() {
        if !finalized, !lastText.isEmpty { finalized = true; onFinal?(lastText) }
        stop()
    }

    func stop() {
        if engine.isRunning {
            engine.stop()
            engine.inputNode.removeTap(onBus: 0)
        }
        request?.endAudio()
        task?.cancel()
        request = nil; task = nil
        if !finalized, !lastText.isEmpty { finalized = true; onFinal?(lastText) }
        if listening { listening = false; onState?(false) }
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
