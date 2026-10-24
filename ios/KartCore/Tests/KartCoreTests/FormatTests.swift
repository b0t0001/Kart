import Foundation
import Testing
@testable import KartCore

@Test func money() {
    #expect(Money.format(Decimal(string: "12.99")!) == "$12.99")
    #expect(Money.format(0) == "$0.00")
    #expect(Money.format(Decimal(string: "1234.5")!) == "$1,234.50")
    #expect(Money.compact(3) == "$3")
    #expect(Money.compact(Decimal(string: "1.5")!) == "$1.50")
}
@Test func tripPhrases() {
    #expect(TripFormat.durationPhrase(seconds: 1380) == "23-minute trip")
    #expect(TripFormat.durationPhrase(seconds: 20) == "1-minute trip")
    #expect(TripFormat.receiptHeadline(savings: Decimal(string: "8.40")!, durationS: 1380) == "You saved $8.40 · 23-minute trip")
    #expect(TripFormat.receiptHeadline(savings: 0, durationS: 240) == "4-minute trip")
}
