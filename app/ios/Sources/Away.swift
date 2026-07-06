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
    You are SCARB, in away mode. You're on your human's phone, away from their Mac, so right now you CANNOT run commands, control the computer, use the terminal, or use your skills — those live on the Mac and come back when it's reachable. You can still think, answer, plan, brainstorm, remember within this chat, and just talk. Be warm, brief, and honest. If they ask you to do something that needs the computer, say plainly that it needs the Mac and offer to do it (or draft it) for when you're reconnected.
    """

    func reset() { messages = []; error = nil }

    func send(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, !busy else { return }
        messages.append(AwayMsg(role: .user, text: t))
        guard configured else { error = "Add a cloud API key in Settings to use SCARB away from your Mac."; return }
        busy = true; error = nil
        let history = messages
        Task {
            defer { busy = false }
            do {
                let reply = try await complete(history)
                messages.append(AwayMsg(role: .scarb, text: reply))
                onReply?(reply)
            } catch {
                self.error = (error as? AwayError)?.message ?? error.localizedDescription
            }
        }
    }

    var onReply: ((String) -> Void)?

    private func complete(_ history: [AwayMsg]) async throws -> String {
        let msgs = history.map { ["role": $0.role == .user ? "user" : "assistant", "content": $0.text] }
        if provider == "anthropic" { return try await anthropic(msgs) }
        return try await openai(msgs)
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

    private func openai(_ msgs: [[String: String]]) async throws -> String {
        let payload: [String: Any] = ["model": activeModel, "max_tokens": 1500,
            "messages": [["role": "system", "content": system]] + msgs]
        let data = try await post(base() + "/chat/completions", payload,
                                  apiKey.isEmpty ? [:] : ["Authorization": "Bearer \(apiKey)"])
        let j = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let choices = j?["choices"] as? [[String: Any]],
           let m = choices.first?["message"] as? [String: Any],
           let c = m["content"] as? String, !c.isEmpty { return c }
        throw AwayError("empty reply")
    }

    private func anthropic(_ msgs: [[String: String]]) async throws -> String {
        let payload: [String: Any] = ["model": activeModel, "max_tokens": 1500,
            "system": system, "messages": msgs]
        let data = try await post(base() + "/messages", payload,
            ["x-api-key": apiKey, "anthropic-version": "2023-06-01"])
        let j = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        if let content = j?["content"] as? [[String: Any]] {
            let text = content.compactMap { $0["text"] as? String }.joined()
            if !text.isEmpty { return text }
        }
        throw AwayError("empty reply")
    }
}

struct AwayError: Error { let message: String; init(_ m: String) { message = m } }
