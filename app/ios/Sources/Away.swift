import Foundation

// "Away mode" — SCARB without the computer. When your Mac's SCARB server is
// unreachable (Mac off, Tailscale down, no network to it), the app talks
// straight to a cloud model from the phone, so you can still chat with SCARB
// anywhere. No tools/terminal/computer-use here (those live on the Mac) — just
// conversation, thinking, and voice. Full powers return when the server is back.

struct AwayMsg: Identifiable, Equatable {
    enum Role { case user, scarb }
    let id = UUID()
    var role: Role
    var text: String
}

@MainActor
final class Away: ObservableObject {
    @Published var provider: String { didSet { save() } }   // anthropic|openrouter|openai|ollama-cloud
    @Published var apiKey: String { didSet { save() } }
    @Published var model: String { didSet { save() } }
    @Published var messages: [AwayMsg] = []
    @Published var busy = false
    @Published var error: String?

    var configured: Bool { !apiKey.isEmpty }

    static let providers = ["anthropic", "openrouter", "openai", "ollama-cloud"]

    init() {
        let d = UserDefaults.standard
        provider = d.string(forKey: "away.provider") ?? "openrouter"
        apiKey = d.string(forKey: "away.key") ?? ""
        model = d.string(forKey: "away.model") ?? ""
    }

    private func save() {
        let d = UserDefaults.standard
        d.set(provider, forKey: "away.provider")
        d.set(apiKey, forKey: "away.key")
        d.set(model, forKey: "away.model")
    }

    static func defaultModel(_ p: String) -> String {
        switch p {
        case "anthropic": return "claude-sonnet-4-6"
        case "openai": return "gpt-4o"
        case "ollama-cloud": return "gpt-oss:120b"
        default: return "anthropic/claude-sonnet-4.6"
        }
    }
    private func base() -> String {
        switch provider {
        case "anthropic": return "https://api.anthropic.com/v1"
        case "openai": return "https://api.openai.com/v1"
        case "ollama-cloud": return "https://ollama.com/v1"
        default: return "https://openrouter.ai/api/v1"
        }
    }
    private var activeModel: String { model.isEmpty ? Self.defaultModel(provider) : model }

    private let system = """
    You are SCARB, in away mode. You're on your human's phone, away from their Mac, so right now you CANNOT run commands, control the computer, use the terminal, or use your Mac skills — those live on the Mac and return when it's reachable. But you DO have the internet: call the web_search tool to look things up, check current facts, prices, news, docs — anything you're unsure of or that may have changed. Don't guess when you can search. You can also think, plan, brainstorm, and remember within this chat. Be warm, brief, and honest. If they ask for something that needs the computer, say it needs the Mac and offer to draft it for when you're reconnected.
    """

    private var currentTask: Task<Void, Never>?

    func reset() { messages = []; error = nil }

    func stop() {
        currentTask?.cancel()
        currentTask = nil
        busy = false
    }

    static func cleanMarkdown(_ t: String) -> String {
        var s = t.replacingOccurrences(of: "```", with: "")
        s = s.replacingOccurrences(of: "**", with: "").replacingOccurrences(of: "`", with: "")
        s = s.replacingOccurrences(of: "*", with: "")
        s = s.replacingOccurrences(of: "^\\s{0,3}#{1,6}\\s*", with: "", options: .regularExpression)
        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func send(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, !busy else { return }
        messages.append(AwayMsg(role: .user, text: t))
        guard configured else { error = "Add a cloud API key in Settings to use SCARB away from your Mac."; return }
        busy = true; error = nil
        let history = messages
        currentTask = Task {
            defer { busy = false; currentTask = nil }
            do {
                let reply = try await complete(history)
                if Task.isCancelled { return }
                let clean = Away.cleanMarkdown(reply)
                messages.append(AwayMsg(role: .scarb, text: clean))
                onReply?(clean)
            } catch {
                if Task.isCancelled { return }
                if let u = error as? URLError, u.code == .cancelled { return }
                self.error = (error as? AwayError)?.message ?? error.localizedDescription
            }
        }
    }

    var onReply: ((String) -> Void)?
    var onSearch: ((String) -> Void)?   // fires when away-SCARB searches the web

    private func complete(_ history: [AwayMsg]) async throws -> String {
        let msgs: [[String: Any]] = history.map { ["role": $0.role == .user ? "user" : "assistant", "content": $0.text] }
        if provider == "anthropic" { return try await anthropicLoop(msgs) }
        return try await openaiLoop(msgs)
    }

    // ---- the web, so away-mode SCARB can look things up ----------------------
    private let webTool: [String: Any] = [
        "type": "function",
        "function": [
            "name": "web_search",
            "description": "Search the web for current or unknown information. Returns top results with titles, URLs, and snippets.",
            "parameters": ["type": "object",
                           "properties": ["query": ["type": "string", "description": "what to search for"]],
                           "required": ["query"]],
        ],
    ]

    private func stripHTML(_ s: String) -> String {
        var t = s.replacingOccurrences(of: "<[^>]+>", with: " ", options: .regularExpression)
        for (a, b) in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&#39;", "'"), ("&quot;", "\""), ("&nbsp;", " ")] {
            t = t.replacingOccurrences(of: a, with: b)
        }
        return t.replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func searchWeb(_ query: String) async -> String {
        let q = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        guard !query.isEmpty, let url = URL(string: "https://html.duckduckgo.com/html/?q=\(q)") else { return "no query" }
        var req = URLRequest(url: url); req.timeoutInterval = 15
        req.setValue("Mozilla/5.0 (iPhone) AppleWebKit/605.1.15", forHTTPHeaderField: "User-Agent")
        do {
            let (data, _) = try await URLSession.shared.data(for: req)
            let html = String(data: data, encoding: .utf8) ?? ""
            let ns = html as NSString
            let linkRe = try NSRegularExpression(pattern: "result__a\"[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", options: [.dotMatchesLineSeparators])
            let snipRe = try NSRegularExpression(pattern: "result__snippet[^>]*>(.*?)</a>", options: [.dotMatchesLineSeparators])
            let links = linkRe.matches(in: html, range: NSRange(location: 0, length: ns.length))
            let snips = snipRe.matches(in: html, range: NSRange(location: 0, length: ns.length))
            var out = "", n = 0
            for m in links {
                let href = ns.substring(with: m.range(at: 1))
                if href.contains("duckduckgo.com/y.js") || href.contains("ad_domain") { continue }
                let title = stripHTML(ns.substring(with: m.range(at: 2)))
                var real = href
                if let r = URLComponents(string: href)?.queryItems?.first(where: { $0.name == "uddg" })?.value { real = r }
                var snip = ""
                if n < snips.count { snip = String(stripHTML(ns.substring(with: snips[n].range(at: 1))).prefix(200)) }
                out += "\(n + 1). \(title)\n\(real)\n\(snip)\n\n"
                n += 1
                if n >= 6 { break }
            }
            return out.isEmpty ? "no results found" : out
        } catch {
            return "search failed: \(error.localizedDescription)"
        }
    }

    private func openaiLoop(_ history: [[String: Any]]) async throws -> String {
        var msgs: [[String: Any]] = [["role": "system", "content": system]] + history
        for _ in 0..<5 {
            let payload: [String: Any] = ["model": activeModel, "max_tokens": 1500, "messages": msgs,
                                          "tools": [webTool], "tool_choice": "auto"]
            let data = try await post(base() + "/chat/completions", payload,
                                      apiKey.isEmpty ? [:] : ["Authorization": "Bearer \(apiKey)"])
            guard let j = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let choices = j["choices"] as? [[String: Any]],
                  let msg = choices.first?["message"] as? [String: Any] else { throw AwayError("bad reply") }
            if let calls = msg["tool_calls"] as? [[String: Any]], !calls.isEmpty {
                msgs.append(msg)
                for tc in calls {
                    let fn = tc["function"] as? [String: Any]
                    var query = ""
                    if let a = fn?["arguments"] as? String,
                       let d = a.data(using: .utf8),
                       let obj = try? JSONSerialization.jsonObject(with: d) as? [String: Any] {
                        query = obj["query"] as? String ?? ""
                    }
                    onSearch?(query)
                    let result = await searchWeb(query)
                    msgs.append(["role": "tool", "tool_call_id": tc["id"] as? String ?? "", "content": result])
                }
                continue
            }
            if let c = msg["content"] as? String, !c.isEmpty { return c }
            throw AwayError("empty reply")
        }
        return "I searched a few times but couldn't wrap it up — try asking again."
    }

    private func anthropicLoop(_ history: [[String: Any]]) async throws -> String {
        let tool: [String: Any] = ["name": "web_search", "description": "Search the web for current or unknown info.",
                                   "input_schema": ["type": "object",
                                                    "properties": ["query": ["type": "string"]], "required": ["query"]]]
        var msgs = history
        for _ in 0..<5 {
            let payload: [String: Any] = ["model": activeModel, "max_tokens": 1500, "system": system,
                                          "messages": msgs, "tools": [tool]]
            let data = try await post(base() + "/messages", payload,
                                      ["x-api-key": apiKey, "anthropic-version": "2023-06-01"])
            guard let j = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let content = j["content"] as? [[String: Any]] else { throw AwayError("bad reply") }
            let uses = content.filter { ($0["type"] as? String) == "tool_use" }
            if !uses.isEmpty {
                msgs.append(["role": "assistant", "content": content])
                var results: [[String: Any]] = []
                for u in uses {
                    let query = (u["input"] as? [String: Any])?["query"] as? String ?? ""
                    onSearch?(query)
                    let r = await searchWeb(query)
                    results.append(["type": "tool_result", "tool_use_id": u["id"] as? String ?? "", "content": r])
                }
                msgs.append(["role": "user", "content": results])
                continue
            }
            let text = content.compactMap { $0["text"] as? String }.joined()
            if !text.isEmpty { return text }
            throw AwayError("empty reply")
        }
        return "I searched a few times but couldn't wrap it up — try again."
    }

    private func post(_ url: String, _ payload: [String: Any], _ headers: [String: String]) async throws -> Data {
        guard let u = URL(string: url) else { throw AwayError("bad URL") }
        var req = URLRequest(url: u); req.httpMethod = "POST"; req.timeoutInterval = 90
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        headers.forEach { req.setValue($1, forHTTPHeaderField: $0) }
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)
        let (data, resp) = try await URLSession.shared.data(for: req)
        if let http = resp as? HTTPURLResponse, http.statusCode >= 400 {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw AwayError("\(http.statusCode): \(body.prefix(200))")
        }
        return data
    }

}

struct AwayError: Error { let message: String; init(_ m: String) { message = m } }
