import Foundation

struct TribeResponse: Decodable {
    let item_id: String?
    let n_timesteps: Int
    let roi_feats: [Double]
    let roi_ts: [String: [Double]]
    let timing: [String: Double]
}

struct AgentReply: Decodable { let text: String; let item_id: String }

/// Thin HTTP client for the Modal TRIBE endpoint and the agent service.
enum BrainSenseClient {
    static func analyze(clip: URL, itemId: String) async throws -> TribeResponse {
        let data = try Data(contentsOf: clip)
        var req = URLRequest(url: Config.serverURL.appendingPathComponent("analyze"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: [
            "video_b64": data.base64EncodedString(), "filename": clip.lastPathComponent,
            "item_id": itemId, "with_raw_embed": false])
        let (body, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return try JSONDecoder().decode(TribeResponse.self, from: body)
    }

    static func ask(itemId: String, question: String) async throws -> AgentReply {
        var req = URLRequest(url: Config.serverURL.appendingPathComponent("agent"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["item_id": itemId, "text": question])
        let (body, _) = try await URLSession.shared.data(for: req)
        return try JSONDecoder().decode(AgentReply.self, from: body)
    }

    static func feedback(itemId: String, liked: Bool) async throws {
        var req = URLRequest(url: Config.serverURL.appendingPathComponent("agent/feedback"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["item_id": itemId, "liked": liked])
        _ = try await URLSession.shared.data(for: req)
    }
}
