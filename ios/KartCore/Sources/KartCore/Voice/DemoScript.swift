import Foundation

/// Scripted lines and plans for the mock agent and the debug panel.
public enum DemoScript {
    public static let greeting = "Hi, I'm Kart. What are we shopping for today?"

    public static let pastaPlan: [PlanItem] = [
        PlanItem(productId: "barilla-spaghetti", reason: "pasta dinner"),
        PlanItem(productId: "rao-marinara", reason: "pasta dinner"),
        PlanItem(productId: "french-baguette", reason: "pasta dinner"),
        PlanItem(productId: "caesar-salad-kit", reason: "side"),
    ]

    public static let tacoPlan: [PlanItem] = [
        "avocados", "mission-tortillas", "ground-beef", "tillamook-mexican-cheese", "tostitos-salsa", "taco-seasoning",
    ].map { PlanItem(productId: $0, reason: "taco night") }

    /// Debug-panel buttons, in demo order.
    public static let userLines = [
        "Pasta dinner for my family, four people.",
        "Yes",
        "No thanks",
        "Taco night for eight.",
        "I'm done.",
    ]
}
