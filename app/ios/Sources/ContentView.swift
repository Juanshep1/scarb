import SwiftUI
import UIKit

// Opens the Tailscale app so you can turn its VPN on (that's what actually
// routes to your Mac away from home). Falls back to the App Store if it's not
// installed.
struct TailscaleButton: View {
    var body: some View {
        Button {
            let app = URL(string: "tailscale://")!
            let store = URL(string: "https://apps.apple.com/app/tailscale/id1470499037")!
            UIApplication.shared.open(app, options: [:]) { ok in
                if !ok { UIApplication.shared.open(store) }
            }
        } label: {
            Label("Open Tailscale", systemImage: "network")
                .font(.callout.bold())
                .padding(.horizontal, 16).padding(.vertical, 9)
                .background(Palette.emerald.opacity(0.15), in: Capsule())
        }
        .foregroundStyle(Palette.emerald)
    }
}

struct ContentView: View {
    @EnvironmentObject var conn: Connection
    @StateObject private var away = Away()
    @State private var reloadToken = 0
    @State private var showSettings = false

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()

            if let url = conn.webURL, case .connected = conn.state {
                SCARBWebView(url: url, reloadToken: $reloadToken) {
                    // web load failed → re-probe (fails over to another host)
                    Task { await conn.probe() }
                }
                .ignoresSafeArea(.container, edges: .bottom)
            } else if conn.state == .offline {
                // Mac unreachable → SCARB still works, chatting on the cloud.
                StandaloneChatView(away: away).environmentObject(conn)
            } else {
                statusScreen
            }

            // a thin status bar with reconnect + settings, always reachable
            VStack {
                HStack(spacing: 10) {
                    statusPill
                    Spacer()
                    Button { reloadToken += 1; Task { await conn.probe() } } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    Button { showSettings = true } label: {
                        Image(systemName: "gearshape.fill")
                    }
                }
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.dim)
                .padding(.horizontal, 16).padding(.vertical, 8)
                .background(.ultraThinMaterial.opacity(0.0))
                Spacer()
            }
            .opacity(overlayVisible ? 1 : 0)
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(reloadToken: $reloadToken).environmentObject(conn)
        }
    }

    // Show the top controls only while searching. The web UI (connected) and the
    // away-mode chat (offline) each have their own chrome.
    private var overlayVisible: Bool {
        if case .searching = conn.state { return true }
        return false
    }

    private var statusPill: some View {
        HStack(spacing: 7) {
            Circle().fill(dotColor).frame(width: 8, height: 8)
            Text(statusText).font(.caption)
        }
    }

    private var dotColor: Color {
        switch conn.state {
        case .connected: return Palette.emerald
        case .searching: return Palette.gold
        case .offline: return Palette.red
        }
    }

    private var statusText: String {
        switch conn.state {
        case .connected(let label): return "connected · \(label)"
        case .searching: return "finding SCARB…"
        case .offline: return "SCARB offline"
        }
    }

    private var statusScreen: some View {
        VStack(spacing: 18) {
            Text("🪲").font(.system(size: 56))
            Text("SCARB").font(.system(size: 22, weight: .black, design: .monospaced))
                .foregroundStyle(Palette.gold).tracking(6)
            switch conn.state {
            case .searching:
                ProgressView().tint(Palette.gold)
                Text("Looking for your computer…\nTailscale or local network.")
                    .multilineTextAlignment(.center).foregroundStyle(Palette.dim)
            case .offline:
                if conn.hasInternet {
                    Text("Online, but can't reach your Mac.")
                        .foregroundStyle(Palette.red)
                    Text("This phone has internet but no route to your Mac — that means **Tailscale isn't connected on this phone**. Open the Tailscale app and turn it on (it should show connected/green). Also make sure your Mac is awake with `scarb.py` running.")
                        .multilineTextAlignment(.center).font(.callout).foregroundStyle(Palette.dim)
                        .padding(.horizontal, 26)
                    TailscaleButton()
                } else {
                    Text("No internet on this phone.")
                        .foregroundStyle(Palette.red)
                    Text("You're offline. When you're back on Wi-Fi or cellular (with Tailscale on), SCARB reconnects on its own.")
                        .multilineTextAlignment(.center).font(.callout).foregroundStyle(Palette.dim)
                        .padding(.horizontal, 30)
                }
                Button("Try again") { Task { await conn.probe() } }
                    .buttonStyle(.borderedProminent).tint(Palette.gold)
                Button("Connection settings") { showSettings = true }
                    .foregroundStyle(Palette.dim)
            case .connected:
                EmptyView()
            }
        }
        .padding()
    }
}
