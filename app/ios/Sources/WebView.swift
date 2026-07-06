import SwiftUI
import WebKit

// Loads the SCARB web UI (the full app — chat, skills, history, settings) from
// whichever host the Connection resolved. Because it's the real web UI, the
// native app has ALL of SCARB's functionality for free; the native part is the
// resilient connection and the shell around it.
struct SCARBWebView: UIViewRepresentable {
    let url: URL
    @Binding var reloadToken: Int
    var onFail: () -> Void

    func makeUIView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.allowsInlineMediaPlayback = true
        cfg.mediaTypesRequiringUserActionForPlayback = []   // let TTS audio autoplay
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true
        // The web mic button hands off to native speech recognition via this.
        cfg.userContentController.add(context.coordinator, name: "mic")
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.navigationDelegate = context.coordinator
        wv.isOpaque = false
        wv.backgroundColor = UIColor(red: 0.043, green: 0.043, blue: 0.072, alpha: 1)
        wv.scrollView.backgroundColor = .clear
        wv.scrollView.bounces = false
        wv.allowsBackForwardNavigationGestures = false
        context.coordinator.webView = wv
        context.coordinator.load(url, into: wv)
        return wv
    }

    func updateUIView(_ wv: WKWebView, context: Context) {
        if context.coordinator.lastToken != reloadToken || context.coordinator.lastURL != url {
            context.coordinator.lastToken = reloadToken
            context.coordinator.load(url, into: wv)
        }
    }

    func makeCoordinator() -> Coordinator { Coordinator(onFail: onFail) }

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        var lastURL: URL?
        var lastToken = -1
        weak var webView: WKWebView?
        let onFail: () -> Void
        private let voice = VoiceInput()

        init(onFail: @escaping () -> Void) {
            self.onFail = onFail
            super.init()
            // stream native speech results back into the web UI
            voice.onState = { [weak self] on in self?.js("window.scarbSetListening && window.scarbSetListening(\(on))") }
            voice.onPartial = { [weak self] t in self?.js("window.scarbSetInput && window.scarbSetInput(\(Self.jsString(t)))") }
            voice.onFinal = { [weak self] t in self?.js("window.scarbVoiceInput && window.scarbVoiceInput(\(Self.jsString(t)))") }
        }

        func load(_ url: URL, into wv: WKWebView) {
            lastURL = url
            var req = URLRequest(url: url)
            req.cachePolicy = .reloadIgnoringLocalCacheData
            wv.load(req)
        }

        // the web mic button posts "start" / "stop" here
        func userContentController(_ ucc: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "mic" else { return }
            let cmd = (message.body as? String) ?? "toggle"
            DispatchQueue.main.async {
                switch cmd {
                case "start": self.voice.start()
                case "stop": self.voice.stop()
                default: self.voice.toggle()
                }
            }
        }

        private func js(_ script: String) {
            DispatchQueue.main.async { self.webView?.evaluateJavaScript(script, completionHandler: nil) }
        }

        private static func jsString(_ s: String) -> String {
            let data = try? JSONSerialization.data(withJSONObject: [s])
            let arr = data.flatMap { String(data: $0, encoding: .utf8) } ?? "[\"\"]"
            return String(arr.dropFirst().dropLast())   // the JSON-escaped element
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { onFail() }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { onFail() }
    }
}
