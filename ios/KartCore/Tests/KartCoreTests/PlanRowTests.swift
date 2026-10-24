import Testing
@testable import KartCore

@Test func planRowsShowHowMany() {
    let one = PlanItem(productId: "mission-tortillas", reason: "tacos", qty: 1, done: false)
    let two = PlanItem(productId: "mission-tortillas", reason: "tacos", qty: 2, done: false)
    #expect(PlanRow.title(one, name: "Tortillas") == "Tortillas")
    #expect(PlanRow.title(two, name: "Tortillas") == "2× Tortillas")
}

@Test func planRowsCountWhatsAlreadyInTheCart() {
    let two = PlanItem(productId: "ground-beef", reason: "tacos", qty: 2, done: false)
    #expect(PlanRow.progress(two, inCart: 0) == nil)
    #expect(PlanRow.progress(two, inCart: 1) == "1 of 2")
    #expect(PlanRow.progress(two, inCart: 2) == nil)           // done: the check mark says it
    #expect(PlanRow.progress(PlanItem(productId: "x", reason: "", qty: 1, done: false), inCart: 0) == nil)
}
