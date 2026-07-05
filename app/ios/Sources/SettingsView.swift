import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var conn: Connection
    @Environment(\.dismiss) private var dismiss
    @Binding var reloadToken: Int

    var body: some View {
        NavigationStack {
            ZStack {
                Palette.bg.ignoresSafeArea()
                Form {
                    Section {
                        ForEach($conn.hosts) { $host in
                            HStack {
                                TextField("label", text: $host.label)
                                    .frame(width: 92)
                                    .foregroundStyle(Palette.dim)
                                Divider()
                                TextField("100.x.y.z or 10.0.0.x", text: $host.address)
                                    .keyboardType(.numbersAndPunctuation)
                                    .autocorrectionDisabled()
                                    .textInputAutocapitalization(.never)
                                    .font(.system(.body, design: .monospaced))
                            }
                        }
                        .onDelete { idx in
                            idx.map { conn.hosts[$0] }.forEach(conn.removeHost)
                        }
                        Button {
                            conn.addHost()
                        } label: {
                            Label("Add a route to your Mac", systemImage: "plus")
                        }
                    } header: {
                        Text("Ways to reach SCARB")
                    } footer: {
                        Text("SCARB tries every route and connects to whichever answers, then keeps checking — so if Tailscale drops, it fails over to your local network automatically. Add your Mac's Tailscale IP (100.x, run `tailscale ip -4`) and its WiFi IP.")
                    }

                    Section("Server") {
                        HStack {
                            Text("Port")
                            Spacer()
                            TextField("8787", value: $conn.port, format: .number)
                                .keyboardType(.numberPad)
                                .multilineTextAlignment(.trailing)
                                .frame(width: 90)
                                .font(.system(.body, design: .monospaced))
                        }
                        SecureField("Access token (if SCARB_TOKEN is set)", text: $conn.token)
                            .autocorrectionDisabled()
                            .textInputAutocapitalization(.never)
                    }

                    Section {
                        Button("Reconnect now") {
                            reloadToken += 1
                            Task { await conn.probe() }
                            dismiss()
                        }
                        .foregroundStyle(Palette.gold)
                    } footer: {
                        Text("SCARB v1 — a native shell over the SCARB server on your computer. The server holds the brain, skills, memory, and computer-use; this app is how you reach it from anywhere.")
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Connection")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}
