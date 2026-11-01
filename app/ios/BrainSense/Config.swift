import Foundation

enum Config {
    static let serverURL = URL(string: ProcessInfo.processInfo.environment["BRAINSENSE_SERVER_URL"] ?? "https://CHANGE-ME:8000")!
    static let clipSeconds: Double = 6
    static let triggerPhrases = ["이거 어때", "어때", "how about this", "what do you think"]
}
