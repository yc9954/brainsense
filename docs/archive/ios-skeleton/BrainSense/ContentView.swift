import SwiftUI

struct ContentView: View {
    @StateObject private var session = GlassesSession()

    var body: some View {
        VStack(spacing: 16) {
            Text("BrainSense").font(.largeTitle.bold())
            Text(session.status).foregroundStyle(.secondary)
            if !session.lastReply.isEmpty {
                Text(session.lastReply).padding().background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
            }
            Button("Connect glasses") { Task { await session.connect() } }
            Button("Ask: 이거 어때?") { Task { await session.askAboutView(question: "이거 어때?") } }
        }
        .padding()
    }
}

@main
struct BrainSenseApp: App {
    var body: some Scene { WindowGroup { ContentView() } }
}
