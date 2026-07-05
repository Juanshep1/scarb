import SwiftUI

struct ContentView: View {
    @EnvironmentObject var conn: Connection
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

    // Show the top controls when disconnected/searching (so you can fix it);
    // hide them once the web UI is up (it has its own chrome).
    private var overlayVisible: Bool {
        if case .connected = conn.state { return false }
        return true
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
                Text("Can't reach SCARB on any route.")
                    .foregroundStyle(Palette.red)
                Text("Make sure `python3 scarb.py` is running on your Mac, and that Tailscale is up or your phone is on the same WiFi.")
                    .multilineTextAlignment(.center).font(.callout).foregroundStyle(Palette.dim)
                    .padding(.horizontal, 30)
                Button("Try again") { Task { await conn.probe() } }
                    .buttonStyle(.borderedProminent).tint(Palette.gold)
                Button("Settings") { showSettings = true }
                    .foregroundStyle(Palette.dim)
            case .connected:
                EmptyView()
            }
        }
        .padding()
    }
}
