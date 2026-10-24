import Foundation

/// What one line of "Your list" says about amounts.
public enum PlanRow {
    /// "2× Tortillas" for more than one, else just the name.
    public static func title(_ line: PlanItem, name: String) -> String {
        line.qty > 1 ? "\(line.qty)× \(name)" : name
    }

    /// "1 of 2" while some but not all are in the cart; nil otherwise (nothing yet, or done).
    public static func progress(_ line: PlanItem, inCart: Int) -> String? {
        line.qty > 1 && inCart > 0 && inCart < line.qty ? "\(inCart) of \(line.qty)" : nil
    }
}
