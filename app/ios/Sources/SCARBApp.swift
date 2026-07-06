import SwiftUI

@main
struct SCARBApp: App {
    @StateObject private var conn = Connection()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(conn)
                .preferredColorScheme(.dark)
                .onAppear { conn.start() }
                // When you come back to the app (got home, back on Wi-Fi,
                // unlocked the phone), iOS had frozen the timer — re-check right
                // away so it reconnects instead of sitting on "can't find it".
                .onChange(of: scenePhase) { newPhase in
                    if newPhase == .active { conn.resume() }
                }
        }
    }
}

enum Palette {
    static let bg = Color(red: 0.043, green: 0.043, blue: 0.072)
    static let panel = Color(red: 0.078, green: 0.075, blue: 0.121)
    static let line = Color(red: 0.149, green: 0.133, blue: 0.219)
    static let ink = Color(red: 0.914, green: 0.914, blue: 0.953)
    static let dim = Color(red: 0.541, green: 0.541, blue: 0.651)
    static let gold = Color(red: 0.909, green: 0.761, blue: 0.455)
    static let emerald = Color(red: 0.31, green: 0.84, blue: 0.63)
    static let red = Color(red: 1.0, green: 0.42, blue: 0.51)
}
