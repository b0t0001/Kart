"""One full shopper trip plus the merchant beat, through Supabase the way the Pi and iPad see it.

  backend/.venv/bin/python -m pytest backend/e2e        # needs a running Supabase + values in .env
"""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from client import ANON, URL, RpcError, kartdb
from psycopg.types.json import Jsonb
from realtime import Watch

# The voice agent plans the basics; the cart's deal cards upsell the rest (nothing is offered
# for items already on the plan).
PASTA = [
    {"product_id": "barilla-spaghetti", "reason": "the pasta"},
    {"product_id": "rao-marinara", "reason": "the sauce"},
]


def cv_event(cart_id, type_, product_id, label, confidence=0.93, method="local", cameras=(0, 1)):
    """An event exactly as the Pi emits it (pi spec §8)."""
    eid = str(uuid.uuid4())
    return {"event_id": eid, "cart_id": cart_id, "type": type_, "product_id": product_id,
            "confidence": confidence, "method": method, "label": label, "cameras": list(cameras),
            "crops": [f"state/crops/{eid}_cam0.jpg"], "ts": "2026-10-24T14:02:11Z"}


def cv_to_rpc(ev):
    """The Pi's HttpSink mapping onto apply_cart_event (CONTRACT §4)."""
    return {"p_cart_id": ev["cart_id"], "p_type": ev["type"], "p_product_id": ev["product_id"],
            "p_confidence": ev["confidence"], "p_source": "vision", "p_label": ev["label"],
            "p_camera": ev["cameras"][0] if ev["cameras"] else None,
            "p_event_id": ev["event_id"], "p_method": ev["method"]}


def merchant(db, applied, tool, args, summary):
    """What the console does on Confirm: a staged change, then merchant_apply (undone after the test)."""
    cid = db.execute("insert into merchant_changes (tool, args, summary, request) values (%s, %s, %s, 'e2e') "
                     "returning id", [tool, Jsonb(args), summary]).fetchone()[0]
    db.execute("select merchant_apply(%s)", [cid])
    applied.append(cid)
    return cid


def qty(cart, pid):
    return next((i["qty"] for i in cart["items"] if i["product_id"] == pid), 0)


def test_full_trip_with_the_merchant_beat(rest, db, cart_id, merchant_changes):
    watch = Watch(URL, ANON, "carts", f"cart_id=eq.{cart_id}")
    parm_deal = f"d-e2e-parm-{uuid.uuid4().hex[:6]}"
    try:
        # The pitch opens without a Parmesan deal; the owner will create it live.
        running = db.execute("select deal_id from product_catalog where id = 'kirkland-parmesan'").fetchone()[0]
        if running:
            merchant(db, merchant_changes, "end_deal", {"deal_id": running}, "End the Parmesan deal")

        # iPad: Welcome tap, then the voice agent's plan
        c = rest.rpc("reset_cart", p_cart_id=cart_id)
        trip = c["trip_id"]
        assert c["status"] == "shopping" and c["items"] == []
        c = rest.rpc("set_plan", p_cart_id=cart_id, p_plan=PASTA)
        assert [p["product_id"] for p in c["plan"]] == ["barilla-spaghetti", "rao-marinara"]
        assert c["next_step"] == "Aisle 6 → Spaghetti"
        line = rest.rpc("append_transcript", p_cart_id=cart_id, p_role="user", p_text="pasta dinner for my family")
        assert line["trip_id"] == trip

        # CV: spaghetti goes in (§8 event), then the outbox retries the same event
        spag = cv_event(cart_id, "added", "barilla-spaghetti", "Barilla Spaghetti, 1 lb")
        c = rest.rpc("apply_cart_event", **cv_to_rpc(spag))
        assert c["total"] == 1.99 and c["location"]["section"] == "A6"
        assert c["suggestion"]["text"] == "Garlic Bread is $1 off in Aisle 8. Want it?"
        c = rest.rpc("apply_cart_event", **cv_to_rpc(spag))
        assert qty(c, "barilla-spaghetti") == 1
        assert len(rest.get("/cart_events", event_id=f"eq.{spag['event_id']}", select="id")) == 1
        seen = watch.wait_for(lambda r: float(r.get("total") or 0) == 1.99)
        assert seen["cart_id"] == cart_id                                        # realtime reached the "iPad"

        # iPad: "No thanks" on the Baguette card
        c = rest.rpc("dismiss_suggestion", p_cart_id=cart_id)
        assert c["suggestion"] is None and "d-baguette-1off" in c["suggested_deals"]

        # Merchant: "parmesan $3 off" confirmed in the console → the cart's card switches live
        merchant(db, merchant_changes, "create_deal", {"deal_id": parm_deal, "product_id": "kirkland-parmesan",
                                     "type": "amount_off", "value": 1, "label": "$1 off", "ends_at": None,
                                     "pairs_with": ["barilla-spaghetti", "rao-marinara"]}, "Parmesan $3 off")
        rec = watch.wait_for(lambda r: (r.get("suggestion") or {}).get("deal_id") == parm_deal)
        assert rec["suggestion"]["text"] == "Parmesan is $1 off in Aisle 4. Want it?"

        # iPad: "Yes" puts it on the plan, which consumes the card (nothing else is eligible now)
        c = rest.rpc("set_plan", p_cart_id=cart_id,
                     p_plan=PASTA + [{"product_id": "kirkland-parmesan", "reason": "said yes to the deal"}])
        assert c["suggestion"] is None and parm_deal in c["suggested_deals"]
        parm_row = next(p for p in c["plan"] if p["product_id"] == "kirkland-parmesan")
        assert parm_row["deal_label"] == "$1 off" and parm_row["aisle"] == "Aisle 4"

        # CV: the shopper takes it (cloud match)
        c = rest.rpc("apply_cart_event", **cv_to_rpc(
            cv_event(cart_id, "added", "kirkland-parmesan", "Grated Parmesan, 8 oz shaker", 0.88, "cloud")))
        parm = next(i for i in c["items"] if i["product_id"] == "kirkland-parmesan")
        assert (parm["price"], parm["list_price"], parm["deal_label"]) == (3.99, 4.99, "$1 off")
        assert c["savings"] == 1.0 and c["suggestion"] is None

        # CV: something it can't identify → confirm card; checkout is blocked until it's answered
        unk = cv_event(cart_id, "added", None, "blue cardboard box, label not visible", 0.31, "none")
        c = rest.rpc("apply_cart_event", **cv_to_rpc(unk))
        assert c["item_count"] == 2
        ev = rest.get("/cart_events", event_id=f"eq.{unk['event_id']}", select="product_id,applied,resolved_at")[0]
        assert ev == {"product_id": None, "applied": False, "resolved_at": None}
        rest.rpc("set_cart_status", p_cart_id=cart_id, p_status="checkout")
        with pytest.raises(RpcError) as blocked:
            rest.rpc("checkout", p_cart_id=cart_id, p_provider="simulated")
        assert blocked.value.status == 400 and blocked.value.body["message"].startswith("unresolved_items: 1 ")

        # iPad: "Is this Rao's?" → Yes
        c = rest.rpc("apply_cart_event", p_cart_id=cart_id, p_type="added", p_product_id="rao-marinara",
                     p_confidence=1.0, p_source="manual", p_label="confirmed by shopper",
                     p_method="manual", p_resolves_event_id=unk["event_id"])
        assert qty(c, "rao-marinara") == 1
        assert rest.get("/cart_events", event_id=f"eq.{unk['event_id']}", select="resolved_at")[0]["resolved_at"]

        # Voice: "I'm at aisle 4"
        c = rest.rpc("set_location", p_cart_id=cart_id, p_section="aisle 4")
        assert c["location"]["section"] == "A4" and c["location"]["source"] == "voice"

        # iPad: Pay
        receipt = rest.rpc("checkout", p_cart_id=cart_id, p_provider="simulated")
        assert (receipt["total"], receipt["savings"], receipt["item_count"]) == (c["total"], 1.0, 3)
        assert receipt["total"] == round(1.99 + 3.99 + 3.49, 2)
        assert receipt["trip_id"] == trip and receipt["status"] == "paid" and receipt["duration_s"] >= 0
        assert rest.rpc("checkout", p_cart_id=cart_id, p_provider="simulated")["id"] == receipt["id"]
        assert rest.get("/carts", cart_id=f"eq.{cart_id}", select="status")[0]["status"] == "paid"
        assert len(rest.get("/receipts", cart_id=f"eq.{cart_id}", select="id")) == 1

        # Next trip: everything for this cart starts clean
        c = rest.rpc("reset_cart", p_cart_id=cart_id)
        assert c["trip_id"] != trip and c["items"] == [] and c["status"] == "shopping"
        assert rest.get("/transcript", cart_id=f"eq.{cart_id}", select="id") == []
    finally:
        watch.close()


def test_anon_key_cannot_touch_what_it_shouldnt(rest, db, cart_id):
    rest.rpc("reset_cart", p_cart_id=cart_id)
    h = rest.http
    assert h.get("/merchant_changes").status_code in (401, 403)
    assert h.patch("/carts", params={"cart_id": f"eq.{cart_id}"}, json={"total": 0}).status_code in (401, 403)
    assert h.patch("/products", params={"id": "eq.bananas"}, json={"price": 0}).status_code in (401, 403)
    for fn, body in [("merchant_apply", {"p_change_id": 1}), ("seed_catalog", {"p_store": {}}),
                     ("recompute_cart", {"p_cart_id": cart_id})]:
        assert h.post(f"/rpc/{fn}", json=body).status_code in (401, 403, 404), fn
    assert float(db.execute("select price from products where id = 'bananas'").fetchone()[0]) == 1.49


def test_catalog_reads_the_ipad_and_cv_use(rest):
    rows = rest.get("/product_catalog", select="id,short_name,sale_price,deal_label,aisle,in_stock,vision_hint")
    n = len(json.loads(kartdb.STORE_JSON.read_text())["products"])
    assert len(rows) == n and all(r["vision_hint"] for r in rows)
    assert len(rest.get("/products", active="is.true", select="id")) == n
    assert {d["id"] for d in rest.get("/deals", select="id")} >= {"d-parm-3off", "d-chips-150off"}


def test_voice_token_function(rest, cart_id):
    rest.rpc("reset_cart", p_cart_id=cart_id)
    fn = URL + "/functions/v1/voice-token"
    headers = {"apikey": ANON, "Authorization": f"Bearer {ANON}"}
    r = httpx.post(fn, json={"cart_id": "no-such-cart"}, headers=headers, timeout=20)
    if r.status_code in (404, 503) and "unknown cart_id" not in r.text:
        pytest.skip(f"voice-token isn't being served here ({r.status_code})")
    assert (r.status_code, r.json()) == (400, {"error": "unknown cart_id"})
    r = httpx.post(fn, json={"cart_id": cart_id}, headers=headers, timeout=20)
    assert r.status_code in (200, 502)          # 502 until a real CARTESIA_API_KEY is set
    body = r.json()
    if r.status_code == 200:
        assert body["token"] and body["ws_url"].startswith("wss://api.cartesia.ai/agents/stream/")
    else:
        assert body["error"] == "cartesia token failed"
    assert "sk_car" not in r.text


def test_yes_moves_on_to_the_next_deal(rest, cart_id):
    rest.rpc("reset_cart", p_cart_id=cart_id)
    ev = lambda pid: cv_to_rpc(cv_event(cart_id, "added", pid, pid))  # noqa: E731
    assert rest.rpc("apply_cart_event", **ev("tostitos-salsa"))["suggestion"]["product_id"] == "tostitos-chips"
    assert rest.rpc("apply_cart_event", **ev("mission-tortillas"))["suggestion"]["product_id"] == "tostitos-chips"
    c = rest.rpc("set_plan", p_cart_id=cart_id, p_plan=[{"product_id": "tostitos-chips", "reason": "said yes"}])
    assert c["suggestion"]["text"] == "Sour Cream is 20% off in Aisle 2. Want it?"


def test_quantity_nudges_beta_on_a_throwaway_cart(rest, cart_id):
    """CONTRACT v0.12: tacos for 4 → 3 bags of avocados → over nudge → keep → walk on (silent) → checkout list."""
    watch = Watch(URL, ANON, "carts", f"cart_id=eq.{cart_id}")
    try:
        rest.rpc("reset_cart", p_cart_id=cart_id)
        c = rest.rpc("set_feature", p_cart_id=cart_id, p_feature="quantity_nudges", p_on=True)
        assert c["features"] == {"quantity_nudges": True}
        assert rest.get("/carts", cart_id=f"eq.{cart_id}", select="features")[0]["features"] == {"quantity_nudges": True}
        rest.rpc("set_plan", p_cart_id=cart_id, p_plan=[
            {"product_id": "mission-tortillas", "qty": 1, "basis": "4 people × 2 tacos ≈ 8 tortillas → 1 pack of 20"},
            {"product_id": "avocados", "qty": 1, "basis": "taco night for 4 → 1 bag of 5"},
            {"product_id": "tostitos-salsa", "qty": 1},
            {"product_id": "tostitos-chips", "qty": 1}])
        for _ in range(3):
            c = rest.rpc("apply_cart_event", **cv_to_rpc(cv_event(cart_id, "added", "avocados", "Hass Avocados")))
        n = c["nudge"]
        assert (n["kind"], n["have"], n["need"], n["savings"]) == ("over", 3, 1, 11.98)
        assert n["text"].startswith("That's 3 Avocados in the cart, and your list needs 1")
        seen = watch.wait_for(lambda r: (r.get("nudge") or {}).get("kind") == "over")
        assert seen["nudge"]["product_id"] == "avocados"              # the iPad gets it over realtime

        c = rest.rpc("dismiss_nudge", p_cart_id=cart_id, p_action="keep")
        assert c["nudge"] is None
        assert next(p for p in c["plan"] if p["product_id"] == "avocados")["qty"] == 3

        # Mid-trip "short" nudges are off (sub-option quantity_nudges_midtrip): walking past the
        # tortillas stays silent; they're on the checkout list instead
        c = rest.rpc("set_location", p_cart_id=cart_id, p_section="aisle 3")
        assert c["nudge"] is None

        # Checkout: everything still short arrives as ONE nudge, answered once
        c = rest.rpc("set_cart_status", p_cart_id=cart_id, p_status="checkout")
        n = c["nudge"]
        assert n["kind"] == "under"
        assert {i["product_id"] for i in n["items"]} == {"mission-tortillas", "tostitos-salsa", "tostitos-chips"}
        assert n["text"].startswith("Before you go: you still need ") and n["product_id"] == n["items"][0]["product_id"]
        c = rest.rpc("dismiss_nudge", p_cart_id=cart_id, p_action="shop")       # "go get them"
        assert c["nudge"] is None and c["status"] == "shopping"

        # Back at checkout with two still short: a shorter list; "skip" is final for the trip
        rest.rpc("apply_cart_event", **cv_to_rpc(cv_event(cart_id, "added", "tostitos-salsa", "Salsa")))
        c = rest.rpc("set_cart_status", p_cart_id=cart_id, p_status="checkout")
        assert {i["product_id"] for i in c["nudge"]["items"]} == {"mission-tortillas", "tostitos-chips"}
        c = rest.rpc("dismiss_nudge", p_cart_id=cart_id, p_action="skip")
        rest.rpc("set_cart_status", p_cart_id=cart_id, p_status="shopping")
        c = rest.rpc("set_cart_status", p_cart_id=cart_id, p_status="checkout")
        assert c["nudge"] is None and "done:tostitos-chips" in c["nudged"]
    finally:
        watch.close()


def test_quantity_nudges_are_off_by_default(rest, cart_id):
    rest.rpc("reset_cart", p_cart_id=cart_id)
    rest.rpc("set_plan", p_cart_id=cart_id, p_plan=[{"product_id": "avocados", "qty": 1}])
    for _ in range(3):
        c = rest.rpc("apply_cart_event", **cv_to_rpc(cv_event(cart_id, "added", "avocados", "Hass Avocados")))
    assert (c["nudge"], c["nudged"], c["features"]) == (None, [], {})


def test_thats_mine_over_rest(rest, cart_id):
    """v0.15: an unrecognized item that's the shopper's own doesn't block Pay and isn't billed."""
    rest.rpc("reset_cart", p_cart_id=cart_id)
    rest.rpc("apply_cart_event", **cv_to_rpc(cv_event(cart_id, "added", "barilla-spaghetti", "Spaghetti")))
    phone = cv_event(cart_id, "added", None, "black rectangle, maybe a phone", 0.2, "none")
    rest.rpc("apply_cart_event", **cv_to_rpc(phone))
    c = rest.rpc("mark_personal", p_cart_id=cart_id, p_event_id=phone["event_id"])
    assert c["total"] == 1.99
    ev = rest.get("/cart_events", event_id=f"eq.{phone['event_id']}", select="resolution")[0]
    assert ev["resolution"] == "personal"
    assert rest.rpc("checkout", p_cart_id=cart_id, p_provider="simulated")["total"] == 1.99


def test_two_meals_voice_edits_and_a_budget_over_rest(rest, cart_id):
    """SHOPPER_INTERACTIONS.md: '…and nachos for Saturday', 'add a queso', 'skip the beans', 'under $30'."""
    rest.rpc("reset_cart", p_cart_id=cart_id)
    c = rest.rpc("set_plan", p_cart_id=cart_id, p_plan=[
        {"product_id": "barilla-spaghetti", "qty": 1, "meal": "Pasta night"},
        {"product_id": "daisy-sour-cream", "qty": 1, "meal": "Taco night"},
        {"product_id": "daisy-sour-cream", "qty": 1, "meal": "Nachos"}])
    sc = next(p for p in c["plan"] if p["product_id"] == "daisy-sour-cream")
    assert (sc["qty"], sc["meals"]) == (2, ["Taco night", "Nachos"])
    c = rest.rpc("add_to_plan", p_cart_id=cart_id, p_product_id="queso", p_qty=1, p_meal="Nachos")
    c = rest.rpc("add_to_plan", p_cart_id=cart_id, p_product_id="black-beans", p_qty=1, p_meal="Nachos")
    c = rest.rpc("remove_from_plan", p_cart_id=cart_id, p_product_id="black-beans")
    assert {p["product_id"] for p in c["plan"]} == {"barilla-spaghetti", "daisy-sour-cream", "queso"}
    c = rest.rpc("set_budget", p_cart_id=cart_id, p_amount=30)
    assert c["budget_left"] == 30 and c["plan_estimate"] == round(1.99 + 2 * 2.39 + 3.99, 2)
