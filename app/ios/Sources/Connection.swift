import SwiftUI
import Combine

// Keeps SCARB reachable. The server is your Mac; there are several ways to get
// to it — Tailscale (works anywhere) and the local network (works on the same
// WiFi even when Tailscale is down). This manager probes every configured host
// and connects to whichever one answers, then keeps checking so that if the
// current path fails it automatically fails over to another. That's the "always
// listens to the computer" promise: as long as ANY route to your Mac is up,
// the app finds it.

struct Host: Identifiable, Codable, Equatable {
    var id = UUID()
    var label: String       // "Tailscale", "WiFi", …
    var address: String     // ip or hostname
}

enum LinkState: Equatable {
    case searching
    case connected(String)  // label of the working host
    case offline
}

@MainActor
final class Connection: ObservableObject {
    @Published var hosts: [Host] { didSet { save() } }
    @Published var port: Int { didSet { save() } }
    @Published var token: String { didSet { save() } }
    @Published var state: LinkState = .searching
    @Published var activeBase: String? = nil    // e.g. http://100.x.y.z:8787

    private var probing = false
    private var timer: Timer?

    init() {
        let d = UserDefaults.standard
        self.port = d.object(forKey: "scarb.port") as? Int ?? 8787
        self.token = d.string(forKey: "scarb.token") ?? ""
        if let data = d.data(forKey: "scarb.hosts"),
           let saved = try? JSONDecoder().decode([Host].self, from: data), !saved.isEmpty {
            self.hosts = saved
        } else {
            // Sensible starting points; the user edits these in Settings.
            // The MagicDNS name works anywhere over Tailscale and is stable even
            // if the IP changes; the raw IP is a fallback; WiFi is for at-home.
            self.hosts = [
                Host(label: "Tailscale", address: "juans-macbook-air.tailc0f840.ts.net"),
                Host(label: "Tailscale IP", address: "100.81.53.119"),
                Host(label: "WiFi", address: "10.0.0.189"),
            ]
        }
    }

    func start() {
        Task { await probe() }
        startTimer()
    }

    private func startTimer() {
        timer?.invalidate()
        // Re-check periodically so a dropped link fails over on its own.
        timer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            Task { await self?.healthCheck() }
        }
    }

    // Called when the app returns to the foreground. iOS suspends the timer
    // while backgrounded, so on resume we restart it and immediately re-check —
    // this is what makes "I got home / back on network" reconnect on its own
    // instead of staying stuck on "can't find the laptop".
    func resume() {
        startTimer()
        Task { await healthCheck() }
    }

    func urlFor(_ host: Host) -> URL? {
        URL(string: "http://\(host.address):\(port)")
    }

    // Probe every host in parallel; connect to the first that responds.
    func probe() async {
        if probing { return }
        probing = true
        defer { probing = false }
        // Only show the "searching" spinner on a fresh look; if we're already in
        // away mode (offline), stay there quietly until we actually reconnect,
        // so a background re-check doesn't yank away the chat.
        if state != .offline { state = .searching }
        let reachable = await firstReachable()
        if let (host, base) = reachable {
            activeBase = base
            state = .connected(host.label)
        } else {
            state = .offline
        }
    }

    // If we think we're connected, verify the current base still answers; if not,
    // re-probe so another route can take over.
    func healthCheck() async {
        guard case .connected = state, let base = activeBase else {
            await probe(); return
        }
        if await ping(base) == false {
            await probe()
        }
    }

    private func firstReachable() async -> (Host, String)? {
        await withTaskGroup(of: (Host, String)?.self) { group in
            for host in hosts where !host.address.trimmingCharacters(in: .whitespaces).isEmpty {
                guard let url = urlFor(host) else { continue }
                let base = url.absoluteString
                group.addTask { [weak self] in
                    (await self?.ping(base) == true) ? (host, base) : nil
                }
            }
            for await result in group {
                if let hit = result {
                    group.cancelAll()
                    return hit
                }
            }
            return nil
        }
    }

    private func ping(_ base: String) async -> Bool {
        guard let url = URL(string: base + "/api/ping") else { return false }
        var req = URLRequest(url: url)
        req.timeoutInterval = 6   // Tailscale/cellular can be slower than LAN
        req.cachePolicy = .reloadIgnoringLocalCacheData
        do {
            let (_, resp) = try await URLSession.shared.data(for: req)
            return (resp as? HTTPURLResponse)?.statusCode == 200
        } catch {
            return false
        }
    }

    // The full URL to load in the web view, carrying the token so the UI is
    // already authenticated.
    var webURL: URL? {
        guard let base = activeBase else { return nil }
        let q = token.isEmpty ? "" : "?token=\(token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")"
        return URL(string: base + "/" + q)
    }

    func addHost() { hosts.append(Host(label: "Host", address: "")) }
    func removeHost(_ host: Host) { hosts.removeAll { $0.id == host.id } }

    private func save() {
        let d = UserDefaults.standard
        d.set(port, forKey: "scarb.port")
        d.set(token, forKey: "scarb.token")
        if let data = try? JSONEncoder().encode(hosts) { d.set(data, forKey: "scarb.hosts") }
    }
}
