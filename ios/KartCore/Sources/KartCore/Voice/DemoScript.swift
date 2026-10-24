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
        "Hey Kart",                                             // member memory beta (after the pasta lines,
        "I'm hosting Friendsgiving next Saturday, ten people.", // so their debug ids stay put)
    ]
}

extension DemoScript {
    /// The live merchant beat: the pitch starts without it, then the owner creates it (contract v0.9).
    public static let parmesanDeal = Deal(id: "d-parm-3off", productId: "kirkland-parmesan", type: .amountOff, value: 1,
                                          label: "$1 off", pairsWith: ["barilla-spaghetti", "rao-marinara"])
    /// A price drop on something already in the cart (P10).
    public static let bananaDeal = Deal(id: "d-bananas-50c", productId: "bananas", type: .amountOff,
                                        value: Decimal(string: "0.5")!, label: "50¢ off", pairsWith: [])
}
