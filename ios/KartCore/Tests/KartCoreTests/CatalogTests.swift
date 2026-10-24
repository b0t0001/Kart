import Foundation
import Testing
@testable import KartCore

@Test func loadsPublishedStoreFile() throws {
    let c = try Fixtures.catalog()
    #expect(c.products.count == 21)
    #expect(c.deals.count == 5)
    #expect(c.layout.sections.count == 10)
    #expect(c.layout.store.width == 20 && c.layout.store.height == 12)
    let parm = try #require(c.product("kirkland-parmesan"))
    #expect(parm.shortName == "Parmesan")
    #expect(parm.price == Decimal(string: "4.99"))
    #expect(parm.section == "A4")
    #expect(parm.stock == 18)
}

@Test func sectionLabels() throws {
    let c = try Fixtures.catalog()
    #expect(c.section("A6")?.aisleLabel == "Aisle 6")
    #expect(c.section("A6")?.title == "Pasta & Sauce")
    #expect(c.section("CK")?.aisleLabel == "Checkout")
    #expect(c.section("CK")?.title == "")
}

@Test func dealsDecodeTypesAndPairs() throws {
    let c = try Fixtures.catalog()
    let sour = try #require(c.deals.first { $0.id == "d-sourcream-20pct" })
    #expect(sour.type == .percentOff && sour.value == 20)
    #expect(c.deals.first { $0.id == "d-parm-3off" }?.pairsWith == ["barilla-spaghetti", "rao-marinara"])
}

@Test func activeDealRespectsEndsAt() throws {
    var c = try Fixtures.catalog()
    let now = Date(timeIntervalSince1970: 1_800_000_000)
    #expect(c.activeDeal(for: "kirkland-parmesan", at: now)?.id == "d-parm-3off")
    c.deals[0].endsAt = now.addingTimeInterval(-1)   // d-parm-3off is first in the file
    #expect(c.activeDeal(for: "kirkland-parmesan", at: now) == nil)
    #expect(c.product("no-such-product") == nil)
}
