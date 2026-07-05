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
        cfg.defaultWebpagePreferences.allowsContentJavaScript = true
        let wv = WKWebView(frame: .zero, configuration: cfg)
        wv.navigationDelegate = context.coordinator
        wv.isOpaque = false
        wv.backgroundColor = UIColor(red: 0.043, green: 0.043, blue: 0.072, alpha: 1)
        wv.scrollView.backgroundColor = .clear
        wv.scrollView.bounces = false
        wv.allowsBackForwardNavigationGestures = false
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

    final class Coordinator: NSObject, WKNavigationDelegate {
        var lastURL: URL?
        var lastToken = -1
        let onFail: () -> Void
        init(onFail: @escaping () -> Void) { self.onFail = onFail }

        func load(_ url: URL, into wv: WKWebView) {
            lastURL = url
            var req = URLRequest(url: url)
            req.cachePolicy = .reloadIgnoringLocalCacheData
            wv.load(req)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) { onFail() }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) { onFail() }
    }
}
