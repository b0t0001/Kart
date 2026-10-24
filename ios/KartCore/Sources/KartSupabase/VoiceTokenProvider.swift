import Foundation
import KartCore

/// Calls the backend's `voice-token` Edge Function (contract P7): the Cartesia key never reaches the iPad.
public struct SupabaseVoiceTokenProvider: VoiceTokenProviding {
    let url: URL
    let anonKey: String
    let session: URLSession

    public init(url: URL, anonKey: String, session: URLSession = .shared) {
        self.url = url
        self.anonKey = anonKey
        self.session = session
    }

    public func token(cartId: String) async throws -> VoiceToken {
        var request = URLRequest(url: url.appending(path: "functions/v1/voice-token"))
        request.httpMethod = "POST"
        request.timeoutInterval = 10
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(anonKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["cart_id": cartId])
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard status == 200 else {
            struct Body: Decodable { let error: String? }
            let message = (try? JSONDecoder().decode(Body.self, from: data))?.error ?? "voice-token failed"
            throw PostgRESTError(status: status, message: message, code: nil)
        }
        return try KartJSON.decoder().decode(VoiceToken.self, from: data)
    }
}
