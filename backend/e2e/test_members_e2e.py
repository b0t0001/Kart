"""Member memory end to end (CONTRACT v0.14, BETA), over PostgREST with the anon key, the way the iPad and the
agent call it: sign in, remember a plan, check out, fast-forward, sign in again, recall. Its own cart and
member (`it-e2e-…`), both removed afterwards. It calls checkout, so it runs on local Supabase only."""

from __future__ import annotations

import uuid
from datetime import timedelta

import httpx
import pytest

from client import URL, RpcError


@pytest.fixture
def member_id(db):
    mid = f"it-e2e-{uuid.uuid4().hex[:8]}"
    yield mid
    db.execute("delete from members where member_id = %s", [mid])


def test_member_round_trip(rest, db, cart_id, member_id):
    if not any(host in URL for host in ("127.0.0.1", "localhost")):   # it checks out: never on hosted (CONTRACT §3)
        pytest.skip("calls checkout, which lowers products.stock for everyone; run it against local Supabase")
    today = db.execute("select (now() at time zone 'America/Los_Angeles')::date").fetchone()[0]
    rest.rpc("reset_cart", p_cart_id=cart_id)

    # The beta is off by default: nothing to sign in to.
    with pytest.raises(RpcError, match="feature_off: member_memory"):
        rest.rpc("set_member", p_cart_id=cart_id, p_member_id=member_id)
    rest.rpc("set_feature", p_cart_id=cart_id, p_feature="member_memory", p_on=True)

    # The sign-in card: an unknown number, confirmed, becomes a member.
    assert rest.rpc("member_lookup", p_member_id=member_id) == {"exists": False, "name": None}
    assert rest.rpc("set_member", p_cart_id=cart_id, p_member_id=member_id)["member_id"] == member_id

    # The agent: "What should I call you?", then a plan for next week with a saved list.
    rest.rpc("member_remember", p_member_id=member_id, p_kind="name", p_text="E2E")
    saved = rest.rpc("member_remember", p_member_id=member_id, p_kind="event", p_text="Friendsgiving, ten people",
                     p_event_date=(today + timedelta(days=7)).isoformat(), p_trip_id=None)
    rest.rpc("member_save_for_later", p_member_id=member_id, p_memory_id=saved["id"],
             p_items=[{"product_id": "barilla-spaghetti", "qty": 3}])

    # Shop and pay: the bill becomes the member's history.
    rest.rpc("apply_cart_event", p_cart_id=cart_id, p_type="added", p_product_id="whole-milk", p_confidence=1.0,
             p_source="manual", p_label="milk", p_method="manual")
    rest.rpc("checkout", p_cart_id=cart_id)

    # The demo fast-forward, a new trip (a guest again), and the same member back.
    later = today + timedelta(days=6)
    rest.rpc("set_demo_date", p_cart_id=cart_id, p_date=later.isoformat())
    assert rest.rpc("reset_cart", p_cart_id=cart_id)["member_id"] is None
    rest.rpc("set_member", p_cart_id=cart_id, p_member_id=member_id)
    profile = rest.rpc("member_profile", p_member_id=member_id, p_cart_id=cart_id)
    assert profile["today"] == later.isoformat() and profile["member"]["name"] == "E2E"
    friends = next(m for m in profile["memories"] if m["text"].startswith("Friendsgiving"))
    assert friends["days_until"] == 1 and friends["upcoming"] is True
    assert friends["items"][0]["product_id"] == "barilla-spaghetti" and friends["items"][0]["qty"] == 3
    assert profile["picks"][0]["product_id"] == "barilla-spaghetti"
    assert profile["picks"][0]["reason"] == "Friendsgiving · tomorrow"
    milk = rest.get("/product_catalog", id="eq.whole-milk", select="short_name")[0]["short_name"]
    assert profile["last_trip"]["date"] == today.isoformat() and profile["last_trip"]["items"] == [milk]

    # Member data is never readable directly with the anon key; only through the RPCs.
    with pytest.raises(httpx.HTTPStatusError):
        rest.get("/members", member_id=f"eq.{member_id}")

    # "Forget me": everything goes, and the cart is signed out.
    assert rest.rpc("member_forget", p_member_id=member_id, p_memory_id=None) == {"forgotten": "all"}
    assert rest.get("/carts", cart_id=f"eq.{cart_id}", select="member_id")[0]["member_id"] is None
    assert rest.rpc("member_lookup", p_member_id=member_id) == {"exists": False, "name": None}
