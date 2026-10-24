import Foundation
import KartCore

/// A JSON value for RPC parameters.
public enum JSONValue: Encodable, Sendable, Equatable {
    case string(String)
    case number(Decimal)
    case bool(Bool)
    case null
    case array([JSONValue])
    case object([String: JSONValue])

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .null: try container.encodeNil()
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        }
    }
}

extension JSONValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByFloatLiteral,
    ExpressibleByBooleanLiteral, ExpressibleByNilLiteral, ExpressibleByArrayLiteral, ExpressibleByDictionaryLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
    public init(integerLiteral value: Int) { self = .number(Decimal(value)) }
    public init(floatLiteral value: Double) { self = .number(Decimal(value)) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
    public init(nilLiteral: ()) { self = .null }
    public init(arrayLiteral elements: JSONValue...) { self = .array(elements) }
    public init(dictionaryLiteral elements: (String, JSONValue)...) { self = .object(Dictionary(uniqueKeysWithValues: elements)) }

    public static func optional(_ value: String?) -> JSONValue { value.map(JSONValue.string) ?? .null }
}

/// A PostgREST error response (`{"code", "message", …}`).
public struct PostgRESTError: Error, Equatable, Sendable {
    public let status: Int
    public let message: String
    public let code: String?

    public init(status: Int, message: String, code: String?) {
        self.status = status
        self.message = message
        self.code = code
    }

    /// The backend's checkout block: `"unresolved_items: N …"`.
    public var unresolvedCount: Int? {
        guard message.hasPrefix("unresolved_items:") else { return nil }
        let digits = message.dropFirst("unresolved_items:".count).drop(while: { $0 == " " }).prefix(while: \.isNumber)
        return Int(digits)
    }
}

/// Just enough PostgREST for the iPad: table reads and RPC calls with the anon key.
public struct PostgREST: Sendable {
    public let url: URL
    private let anonKey: String
    private let session: URLSession

    public init(url: URL, anonKey: String, session: URLSession = .shared) {
        self.url = url
        self.anonKey = anonKey
        self.session = session
    }

    /// `path` is a table or view plus its query string, e.g. `"carts?cart_id=eq.7"`.
    public func select<T: Decodable & Sendable>(_ path: String, as type: T.Type = T.self) async throws -> [T] {
        let data = try await send(request("rest/v1/\(path)", method: "GET"))
        return try KartJSON.decoder().decode([T].self, from: data)
    }

    public func rpc<T: Decodable>(_ name: String, _ params: [String: JSONValue], as type: T.Type = T.self) async throws -> T {
        let data = try await send(rpcRequest(name, params))
        return try KartJSON.decoder().decode(T.self, from: data)
    }

    public func rpc(_ name: String, _ params: [String: JSONValue]) async throws {
        _ = try await send(rpcRequest(name, params))
    }

    private func rpcRequest(_ name: String, _ params: [String: JSONValue]) throws -> URLRequest {
        var request = request("rest/v1/rpc/\(name)", method: "POST")
        request.httpBody = try JSONEncoder().encode(params)
        return request
    }

    private func request(_ path: String, method: String) -> URLRequest {
        let base = url.absoluteString.hasSuffix("/") ? url.absoluteString : url.absoluteString + "/"
        var request = URLRequest(url: URL(string: base + path)!)
        request.httpMethod = method
        request.timeoutInterval = 10
        request.setValue(anonKey, forHTTPHeaderField: "apikey")
        request.setValue("Bearer \(anonKey)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    private func send(_ request: URLRequest) async throws -> Data {
        let (data, response) = try await session.data(for: request)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            struct Body: Decodable { let message: String?; let code: String? }
            let body = try? JSONDecoder().decode(Body.self, from: data)
            throw PostgRESTError(status: status, message: body?.message ?? String(decoding: data, as: UTF8.self), code: body?.code)
        }
        return data
    }
}
