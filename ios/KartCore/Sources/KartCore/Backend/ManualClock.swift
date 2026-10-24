import Foundation

/// A clock tests and demo scenarios can move by hand.
@MainActor public final class ManualClock {
    public var now: Date

    public init(now: Date = Date(timeIntervalSince1970: 1_800_000_000)) {
        self.now = now
    }
}
