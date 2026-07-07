import SwiftUI
import AVFoundation

struct StandaloneChatView: View {
    @EnvironmentObject var conn: Connection
    @ObservedObject var away: Away
    @State private var input = ""
    @State private var showSettings = false
    @State private var searchNote = ""
    @StateObject private var voice = VoiceBox()

    var body: some View {
        ZStack {
            Palette.bg.ignoresSafeArea()
            VStack(spacing: 0) {
                header
                banner
                messages
                composer
            }
        }
        .sheet(isPresented: $showSettings) { AwaySettingsView(away: away) }
        .onAppear {
            away.onReply = { text in searchNote = ""; voice.speak(text) }
            away.onSearch = { q in searchNote = q }
            voice.onFinal = { text in input = ""; away.send(text) }
        }
    }

    private var header: some View {
        HStack(spacing: 10) {
            Text("🪲").font(.title2)
            VStack(alignment: .leading, spacing: 1) {
                Text("SCARB").font(.system(size: 15, weight: .black, design: .monospaced))
                    .foregroundStyle(Palette.gold).tracking(3)
                Text("away mode · \(away.provider)").font(.caption2).foregroundStyle(Palette.dim)
            }
            Spacer()
            Button { away.reset() } label: { Image(systemName: "square.and.pencil") }
            Button { showSettings = true } label: { Image(systemName: "gearshape.fill") }
        }
        .foregroundStyle(Palette.dim)
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(Palette.panel)
    }

    private var banner: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 8) {
                Image(systemName: "wifi.slash").font(.caption2)
                Text("Your Mac isn't reachable — chatting on the cloud. Full powers return when it's back.")
                    .font(.caption2)
                Spacer(minLength: 0)
                Button("Retry") { Task { await conn.probe() } }.font(.caption2.bold())
            }
            if conn.hasInternet {
                // Online but no route to the Mac. With Tailscale connected, the
                // usual culprit is iOS's Local Network permission (it gates
                // Tailscale 100.x addresses). Offer both fixes.
                Text("Online but can't reach your Mac. If Tailscale is ON here, iOS may be blocking it — allow SCARB's Local Network access. Also make sure your Mac is awake.")
                    .font(.caption2)
                HStack(spacing: 8) {
                    AppSettingsButton().scaleEffect(0.85)
                    TailscaleButton().scaleEffect(0.85)
                    Spacer(minLength: 0)
                }
            }
        }
        .foregroundStyle(Palette.gold)
        .padding(.horizontal, 14).padding(.vertical, 7)
        .background(Palette.gold.opacity(0.08))
    }

    private var messages: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if away.messages.isEmpty {
                        VStack(spacing: 10) {
                            Text("🪲").font(.system(size: 44))
                            Text(away.configured
                                 ? "I'm here even without your Mac — and I can search the web. Ask me anything."
                                 : "Add a cloud API key in Settings to chat away from your Mac.")
                                .multilineTextAlignment(.center).foregroundStyle(Palette.dim)
                                .padding(.horizontal, 30)
                            if !away.configured {
                                Button("Set up") { showSettings = true }
                                    .buttonStyle(.borderedProminent).tint(Palette.gold)
                            }
                        }.frame(maxWidth: .infinity).padding(.top, 60)
                    }
                    ForEach(away.messages) { m in bubble(m) }
                    if away.busy {
                        HStack(spacing: 8) { ProgressView().tint(Palette.gold)
                            Text(searchNote.isEmpty ? "thinking…" : "🌐 searching: \(searchNote)")
                                .font(.caption).foregroundStyle(Palette.dim) }
                    }
                    if let e = away.error {
                        Text(e).font(.caption).foregroundStyle(Palette.red)
                            .padding(10).background(Palette.panel, in: RoundedRectangle(cornerRadius: 10))
                    }
                    Color.clear.frame(height: 1).id("end")
                }.padding(14)
            }
            .onChange(of: away.messages.count) { _ in withAnimation { proxy.scrollTo("end") } }
        }
    }

    private func bubble(_ m: AwayMsg) -> some View {
        HStack {
            if m.role == .user { Spacer(minLength: 40) }
            VStack(alignment: m.role == .user ? .trailing : .leading, spacing: 4) {
                if m.role == .scarb {
                    Text("SCARB").font(.caption2.bold()).foregroundStyle(Palette.gold)
                }
                Text(m.text)
                    .foregroundStyle(Palette.ink)
                    .padding(.horizontal, 14).padding(.vertical, 10)
                    .background(m.role == .user ? Palette.line : Palette.panel,
                                in: RoundedRectangle(cornerRadius: 14))
            }
            if m.role == .scarb { Spacer(minLength: 40) }
        }
    }

    private var composer: some View {
        HStack(spacing: 10) {
            Button {
                voice.toggle()
            } label: {
                Image(systemName: voice.listening ? "mic.fill" : "mic")
                    .foregroundStyle(voice.listening ? Palette.red : Palette.dim)
                    .frame(width: 40, height: 40)
                    .background(Palette.panel, in: RoundedRectangle(cornerRadius: 12))
            }
            TextField("Ask SCARB…", text: $input, axis: .vertical)
                .lineLimit(1...4)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Palette.panel, in: RoundedRectangle(cornerRadius: 18))
                .foregroundStyle(Palette.ink)
            if away.busy {
                Button {
                    away.stop(); voice.stopSpeaking()
                } label: {
                    Image(systemName: "stop.circle.fill").font(.system(size: 30))
                        .foregroundStyle(Palette.red)
                }
            } else {
                Button {
                    let t = input; input = ""; away.send(t)
                } label: {
                    Image(systemName: "arrow.up.circle.fill").font(.system(size: 30))
                        .foregroundStyle(Palette.gold)
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(Palette.panel.opacity(0.6))
    }
}

// Native voice: on-device speech-in (reusing VoiceInput) and speech-out.
@MainActor
final class VoiceBox: ObservableObject {
    @Published var listening = false
    private let input = VoiceInput()
    private let synth = AVSpeechSynthesizer()
    var onFinal: ((String) -> Void)?

    init() {
        input.onState = { [weak self] on in self?.listening = on }
        input.onFinal = { [weak self] text in self?.onFinal?(text) }
    }
    func toggle() { input.toggle() }
    func stopSpeaking() { synth.stopSpeaking(at: .immediate) }
    func speak(_ text: String) {
        let clean = text.replacingOccurrences(of: "*", with: "").replacingOccurrences(of: "#", with: "")
        let u = AVSpeechUtterance(string: String(clean.prefix(1200)))
        u.rate = 0.5
        try? AVAudioSession.sharedInstance().setCategory(.playback, options: .duckOthers)
        synth.speak(u)
    }
}
