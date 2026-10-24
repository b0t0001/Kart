import Foundation

public enum Money {
    private static let usd = Decimal.FormatStyle.Currency(code: "USD", locale: Locale(identifier: "en_US"))

    /// "$12.99", "$0.00", "$1,234.50".
    public static func format(_ amount: Decimal) -> String {
        amount.formatted(usd)
    }

    /// Like `format`, but whole dollars drop the cents: "$3", "$1.50".
    public static func compact(_ amount: Decimal) -> String {
        isWhole(amount) ? amount.formatted(usd.precision(.fractionLength(0))) : format(amount)
    }

    private static func isWhole(_ amount: Decimal) -> Bool {
        var value = amount
        var rounded = Decimal()
        NSDecimalRound(&rounded, &value, 0, .plain)
        return rounded == amount
    }
}

public enum TripFormat {
    /// "23-minute trip", rounded to the nearest minute, at least 1.
    public static func durationPhrase(seconds: Int) -> String {
        "\(max(1, (seconds + 30) / 60))-minute trip"
    }

    /// "You saved $8.40 · 23-minute trip", or just the duration when nothing was saved.
    public static func receiptHeadline(savings: Decimal, durationS: Int) -> String {
        let duration = durationPhrase(seconds: durationS)
        return savings > 0 ? "You saved \(Money.format(savings)) · \(duration)" : duration
    }
}
