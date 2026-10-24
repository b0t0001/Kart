import Foundation

/// JSON settings shared by every Supabase row and the bundled catalog.
public enum KartJSON {
    public static func decoder() -> JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let text = try container.decode(String.self)
            guard let date = parseTimestamp(text) else {
                throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unrecognized timestamp: \(text)")
            }
            return date
        }
        return decoder
    }

    /// Accepts `Z` or `±hh[:mm]` offsets, a `T` or space separator, and a fraction of any length
    /// (Postgres `timestamptz` sends microseconds).
    static func parseTimestamp(_ text: String) -> Date? {
        let pattern = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?(Z|[+-]\d{2}(?::?\d{2})?)?$/
        guard let match = text.wholeMatch(of: pattern) else { return nil }
        let zone = normalizedZone(match.4.map(String.init) ?? "Z")
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        guard let base = formatter.date(from: "\(match.1)T\(match.2)\(zone)") else { return nil }
        let fraction = match.3.flatMap { Double("0" + $0) } ?? 0
        return base.addingTimeInterval(fraction)
    }

    private static func normalizedZone(_ zone: String) -> String {
        guard zone != "Z" else { return zone }
        let digits = zone.dropFirst().filter(\.isNumber)
        let hours = digits.prefix(2)
        let minutes = digits.count >= 4 ? digits.suffix(2) : "00"
        return "\(zone.first!)\(hours):\(minutes)"
    }
}
