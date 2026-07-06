import SwiftUI

struct AwaySettingsView: View {
    @ObservedObject var away: Away
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Palette.bg.ignoresSafeArea()
                Form {
                    Section {
                        Picker("Provider", selection: $away.provider) {
                            Text("Anthropic (Claude)").tag("anthropic")
                            Text("OpenRouter").tag("openrouter")
                            Text("OpenAI").tag("openai")
                            Text("Ollama Cloud").tag("ollama-cloud")
                        }
                        SecureField("API key", text: $away.apiKey)
                            .autocorrectionDisabled().textInputAutocapitalization(.never)
                        TextField("Model (blank = default)", text: $away.model)
                            .autocorrectionDisabled().textInputAutocapitalization(.never)
                            .font(.system(.body, design: .monospaced))
                    } header: {
                        Text("SCARB anywhere (away mode)")
                    } footer: {
                        Text("When your Mac's SCARB server can't be reached, the app chats with SCARB directly through this cloud model — so it still works from anywhere. Your key is stored only on this device. Default model: \(Away.defaultModel(away.provider)).")
                    }
                }
                .scrollContentBackground(.hidden)
            }
            .navigationTitle("Away mode")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }
}
