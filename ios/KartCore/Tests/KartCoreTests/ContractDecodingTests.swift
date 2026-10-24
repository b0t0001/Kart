import Foundation
import Testing
@testable import KartCore

/// Minimal v0.3-era row: none of the §3a / P-item fields.
let cartRowMinimal = #"""
{"cart_id":"7","trip_id":"6F9619FF-8B86-D011-B42D-00C04FC964FF",
 "items":[{"product_id":"kirkland-parmesan","name":"Kirkland Signature Parmigiano Reggiano, 1.5 lb wedge",
           "price":9.99,"qty":1,"deal_label":"$3 off","added_at":"2026-10-24T18:02:11.123456+00:00"}],
 "total":9.99,"plan":[{"product_id":"barilla-spaghetti","reason":"pasta dinner","done":false}],
 "next_step":"Aisle 6 → Spaghetti","lcd_line1":"A6 Spaghetti",
 "suggestion":{"product_id":"french-baguette","deal_id":"d-baguette-1off","text":"Baguette is $1 off in Aisle 2. Want it?"},
 "updated_at":"2026-10-24T18:02:11Z"}
"""#
/// As-built v0.8 row (§3a + P2/P3/P8).
let cartRowV08 = #"""
{"cart_id":"7","trip_id":"6F9619FF-8B86-D011-B42D-00C04FC964FF","status":"shopping","trip_started_at":"2026-10-24T18:00:00Z",
 "items":[{"product_id":"kirkland-parmesan","name":"Kirkland Signature Parmigiano Reggiano, 1.5 lb wedge","short_name":"Parmesan",
           "price":9.99,"list_price":12.99,"qty":2,"deal_label":"$3 off","deal_id":"d-parm-3off","section":"A4",
           "added_at":"2026-10-24T18:02:11Z","last_added_at":"2026-10-24T18:04:00Z"}],
 "item_count":2,"total":19.98,"savings":6.0,"suggested_deals":["d-parm-3off"],
 "plan":[{"product_id":"kirkland-parmesan","reason":"deal","qty":1,"done":true,"name":"Parmesan","section":"A4","aisle":"Aisle 4","in_stock":true,"deal_label":"$3 off"}],
 "next_step":"All done → Checkout","suggestion":null,
 "location":{"section":"A4","source":"item","at":"2026-10-24T18:04:00Z"},"updated_at":"2026-10-24T18:04:00Z"}
"""#

@Test func decodesCartRowWithoutProposedFields() throws {
    let cart = try KartJSON.decoder().decode(CartState.self, from: Data(cartRowMinimal.utf8))
    #expect(cart.cartId == "7")
    #expect(cart.items[0].price == Decimal(string: "9.99"))
    #expect(cart.items[0].dealLabel == "$3 off" && cart.items[0].listPrice == nil && cart.items[0].shortName == nil)
    #expect(cart.plan.map(\.productId) == ["barilla-spaghetti"] && cart.plan[0].qty == 1 && !cart.plan[0].done)
    #expect(cart.suggestion?.dealId == "d-baguette-1off")
    #expect(cart.status == .idle)          // no status field → default
    #expect(cart.savings == nil && cart.location == nil && cart.tripStartedAt == nil)
    #expect(cart.itemCount == 1 && cart.suggestedDeals.isEmpty)
}
@Test func decodesAsBuiltRow() throws {
    let cart = try KartJSON.decoder().decode(CartState.self, from: Data(cartRowV08.utf8))
    #expect(cart.status == .shopping && cart.tripStartedAt != nil)
    #expect(cart.itemCount == 2 && cart.savings == 6 && cart.suggestedDeals == ["d-parm-3off"])
    #expect(cart.items[0].shortName == "Parmesan" && cart.items[0].listPrice == Decimal(string: "12.99") && cart.items[0].section == "A4")
    #expect(cart.plan[0].aisle == "Aisle 4" && cart.plan[0].inStock == true && cart.plan[0].done)
    #expect(cart.location?.section == "A4" && cart.suggestion == nil)
}
@Test func decodesCartEventAndFlagsConfirmation() throws {
    let row = #"{"id":12,"event_id":"0E984725-C51C-4BF4-9960-E1C80E27ABA0","cart_id":"7","trip_id":"6F9619FF-8B86-D011-B42D-00C04FC964FF","type":"added","product_id":null,"confidence":0.41,"source":"vision","camera":0,"label":"red jar of tomato sauce","snapshot_url":null,"method":"cloud","applied":false,"created_at":"2026-10-24T18:03:00.5+00:00","resolved_at":null}"#
    var e = try KartJSON.decoder().decode(CartEvent.self, from: Data(row.utf8))
    #expect(e.id == 12 && e.needsConfirmation && e.tripId != nil)
    e.resolvedAt = .now;  #expect(!e.needsConfirmation)
    e.resolvedAt = nil; e.productId = "made-up-id"; e.applied = false
    #expect(e.needsConfirmation)          // an unknown product id isn't applied either
}
@Test func decodesReceiptRow() throws {
    let row = #"{"id":3,"cart_id":"7","trip_id":"6F9619FF-8B86-D011-B42D-00C04FC964FF","total":22.46,"savings":4.0,"item_count":4,"duration_s":1380,"provider":"simulated","status":"paid","items":[],"created_at":"2026-10-24T18:23:00Z"}"#
    let r = try KartJSON.decoder().decode(Receipt.self, from: Data(row.utf8))
    #expect(r.total == Decimal(string: "22.46") && r.itemCount == 4 && r.durationS == 1380 && r.status == "paid")
}
@Test func parsesAllTimestampShapes() throws {
    struct T: Decodable { let a: Date; let b: Date; let c: Date }
    let t = try KartJSON.decoder().decode(T.self, from: Data(#"{"a":"2026-10-24T18:02:11Z","b":"2026-10-24T18:02:11.000+00:00","c":"2026-10-24T18:02:11.123456+00:00"}"#.utf8))
    #expect(t.a == t.b)
    #expect(abs(t.c.timeIntervalSince(t.a) - 0.123) < 0.001)
}
