"""Merchant agent: staging, confirm/undo, live effect on carts, the agent loop, the console API."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import anthropic
import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from agent import STORE_TZ, MerchantAgent, ToolError
from server import create_app


def product(store, pid):
    return store.product(pid)


def add_to_cart(store, pid):
    store.q("select apply_cart_event('7', 'added', %s, 0.9, 'vision', %s)", [pid, pid])


def cart(store):
    return store.cart("7")


def stage(tools, tool, /, **inp):
    _, change = tools.run(tool, inp, "test")
    return change


# ── Writes only stage ──

def test_staging_changes_nothing_until_confirmed(store, tools):
    add_to_cart(store, "barilla-spaghetti")
    ch = stage(tools, "create_deal", product_id="barilla-spaghetti", type="amount_off", value=1,
               ends_at=None, pairs_with=["rao-marinara"])
    assert ch["status"] == "pending"
    assert product(store, "barilla-spaghetti")["deal_id"] is None
    assert cart(store)["items"][0]["price"] == 1.99

    store.apply(ch["id"])
    p = product(store, "barilla-spaghetti")
    assert (p["deal_label"], float(p["sale_price"])) == ("$1 off", 0.99)
    assert cart(store)["items"][0]["price"] == 0.99          # the demo moment: the cart drops live


def test_cancel_leaves_catalog_alone(store, tools):
    ch = stage(tools, "set_stock", product_id="rao-marinara", stock=0)
    assert store.cancel(ch["id"])["status"] == "cancelled"
    assert product(store, "rao-marinara")["stock"] == 24
    with pytest.raises(psycopg.errors.RaiseException):
        store.apply(ch["id"])


def test_confirm_twice_is_refused(store, tools):
    ch = stage(tools, "set_stock", product_id="rao-marinara", stock=0)
    store.apply(ch["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="already applied"):
        store.apply(ch["id"])


# ── Previews ──

def test_price_preview_reads_plainly(store, tools):
    add_to_cart(store, "kirkland-parmesan")
    text, ch = tools.run("update_price", {"product_id": "kirkland-parmesan", "new_price": 11.99}, "test")
    assert ch["summary"] == ("Change the price of Parmesan (Kirkland Signature Parmigiano Reggiano, 1.5 lb wedge) "
                             "from $12.99 to $11.99. With its $3 off deal, shoppers pay $8.99. "
                             "1 cart with it now gets the lower price right away.")
    assert "NOT applied" in text


def test_price_increase_preview_says_carts_keep_their_price(store, tools):
    add_to_cart(store, "bananas")
    ch = stage(tools, "update_price", product_id="bananas", new_price=1.99)
    assert "1 cart with it now keeps the price its shopper saw." in ch["summary"]


def test_out_of_stock_preview(store, tools):
    ch = stage(tools, "set_stock", product_id="rao-marinara", stock=0)
    assert ch["summary"].startswith("Set Rao's Sauce stock from 24 to 0 (out of stock).")


def test_deal_preview_with_end_date_and_pairing(store, tools):
    sunday = (datetime.now(STORE_TZ) + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)
    ch = stage(tools, "create_deal", product_id="kirkland-parmesan", type="amount_off", value=4,
               ends_at=sunday.isoformat(), pairs_with=["barilla-spaghetti", "rao-marinara"])
    s = ch["summary"]
    assert s.startswith("New deal: Parmesan $4 off ($8.99 instead of $12.99), through ")
    assert "11:59 PM" in s
    assert "when a shopper picks up Spaghetti or Rao's Sauce" in s
    assert "Replaces the current $3 off deal." in s


# ── Each tool, applied ──

def test_move_product_updates_directions(store, tools):
    store.q("""select set_plan('7', '[{"product_id": "kirkland-parmesan", "reason": "topping"}]')""")
    store.apply(stage(tools, "move_product", product_id="kirkland-parmesan", section="A6")["id"])
    assert cart(store)["next_step"] == "Aisle 6 → Parmesan, $3 off"


def test_out_of_stock_reaches_plans(store, tools):
    store.q("""select set_plan('7', '[{"product_id": "rao-marinara", "reason": "sauce"}]')""")
    store.apply(stage(tools, "set_stock", product_id="rao-marinara", stock=0)["id"])
    assert cart(store)["plan"][0]["in_stock"] is False


def test_add_product_then_undo_delists_it(store, tools):
    ch = stage(tools, "add_product", name="Fresh Basil, 0.75 oz", short_name="Basil", price=2.49, section="A1",
               category="Produce", tags=["pasta", "Italian"], stock=20,
               vision_hint="small clear clamshell of bright green basil leaves")
    assert ch["args"]["id"] == "fresh-basil-0-75-oz"
    assert ch["summary"].endswith("Cart cameras will look for: small clear clamshell of bright green basil leaves")
    store.apply(ch["id"])
    assert product(store, "fresh-basil-0-75-oz")["tags"] == ["italian", "pasta"]
    store.undo(ch["id"])
    assert product(store, "fresh-basil-0-75-oz") is None


def test_new_deal_replaces_old_and_undo_restores_it(store, tools):
    ch = stage(tools, "create_deal", product_id="kirkland-parmesan", type="percent_off", value=25,
               ends_at=None, pairs_with=["barilla-spaghetti"])
    store.apply(ch["id"])
    p = product(store, "kirkland-parmesan")
    assert (p["deal_label"], float(p["sale_price"])) == ("25% off", 9.74)
    assert not store.one("select active from deals where id = 'd-parm-3off'")["active"]
    store.undo(ch["id"])
    assert product(store, "kirkland-parmesan")["deal_id"] == "d-parm-3off"


def test_end_deal_keeps_price_for_carts_that_have_it(store, tools):
    add_to_cart(store, "kirkland-parmesan")
    store.apply(stage(tools, "end_deal", deal_id="d-parm-3off")["id"])
    assert product(store, "kirkland-parmesan")["deal_id"] is None
    assert cart(store)["items"][0]["price"] == 9.99           # P10: the price you saw


def test_undo_restores_price_and_is_logged(store, tools):
    ch = stage(tools, "update_price", product_id="barilla-spaghetti", new_price=2.49)
    store.apply(ch["id"])
    u = store.undo(ch["id"])
    assert (u["tool"], u["status"], u["undo_of"]) == ("undo", "applied", ch["id"])
    assert float(product(store, "barilla-spaghetti")["price"]) == 1.99
    assert store.change(ch["id"])["status"] == "undone"
    with pytest.raises(psycopg.errors.RaiseException):
        store.undo(ch["id"])                                  # can't undo twice


def test_staged_undo_tool(store, tools):
    ch = stage(tools, "set_stock", product_id="rao-marinara", stock=0)
    store.apply(ch["id"])
    u = stage(tools, "undo_change", change_id=ch["id"])
    assert u["summary"].startswith(f"Undo change #{ch['id']}: Set Rao's Sauce stock")
    store.apply(u["id"])
    assert product(store, "rao-marinara")["stock"] == 24


# ── Safety rails ──

def test_stale_preview_is_refused(store, tools):
    ch = stage(tools, "update_price", product_id="barilla-spaghetti", new_price=1.49)
    store.q("update products set price = 2.29 where id = 'barilla-spaghetti'")   # someone else changed it
    with pytest.raises(psycopg.errors.RaiseException, match="stale"):
        store.apply(ch["id"])


def test_undo_refuses_to_clobber_a_newer_change(store, tools):
    a = stage(tools, "update_price", product_id="barilla-spaghetti", new_price=2.49)
    store.apply(a["id"])
    store.apply(stage(tools, "update_price", product_id="barilla-spaghetti", new_price=2.99)["id"])
    with pytest.raises(psycopg.errors.RaiseException, match="stale"):
        store.undo(a["id"])
    assert float(product(store, "barilla-spaghetti")["price"]) == 2.99


@pytest.mark.parametrize("name,inp,msg", [
    ("update_price", {"product_id": "nope", "new_price": 1}, "No product"),
    ("update_price", {"product_id": "bananas", "new_price": 1.49}, "already"),
    ("create_deal", {"product_id": "bananas", "type": "amount_off", "value": 5, "ends_at": None,
                     "pairs_with": []}, "between"),
    ("create_deal", {"product_id": "bananas", "type": "amount_off", "value": 0.5,
                     "ends_at": "2020-01-01T00:00:00-08:00", "pairs_with": []}, "past"),
    ("create_deal", {"product_id": "bananas", "type": "amount_off", "value": 0.5, "ends_at": None,
                     "pairs_with": ["ghost"]}, "No product"),
    ("add_product", {"name": "Thing", "short_name": "A very long name", "price": 1, "section": "A1",
                     "category": "x", "tags": [], "stock": 1, "vision_hint": "box"}, "11 characters"),
    ("move_product", {"product_id": "bananas", "section": "A1"}, "already"),
    ("add_product", {"name": "Thing", "short_name": "Thing", "price": 1, "section": "A1",
                     "category": "x", "tags": [], "stock": 1, "vision_hint": "  "}, "vision_hint is required"),
    ("end_deal", {"deal_id": "d-nope"}, "No running deal"),
    ("undo_change", {"change_id": 999}, "can't be undone"),
])
def test_bad_requests_are_tool_errors(tools, name, inp, msg):
    with pytest.raises(ToolError, match=msg):
        tools.run(name, inp, "test")


def test_anon_cannot_see_or_apply_changes(store, tools, db_url):
    ch = stage(tools, "set_stock", product_id="rao-marinara", stock=0)
    with psycopg.connect(db_url) as c:
        c.execute("set local role anon")
        for sql in ["select * from merchant_changes", f"select merchant_apply({ch['id']})"]:
            c.execute("savepoint s")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql)
            c.execute("rollback to savepoint s")
        c.rollback()


# ── Search ──

@pytest.mark.parametrize("query,first", [("raos", "rao-marinara"), ("Rao's sauce", "rao-marinara"),
                                         ("parm", "kirkland-parmesan"), ("tortilla chips", "tostitos-chips")])
def test_search_finds_what_people_say(tools, query, first):
    assert json.loads(tools.search_products(query))[0]["id"] == first


def test_empty_search_lists_everything(tools):
    assert len(json.loads(tools.search_products(""))) == 18


# ── The agent loop (scripted fake Claude) ──

def tool_use(id_, name, **inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


def text(t):
    return SimpleNamespace(type="text", text=t)


class FakeClaude:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(stop, *content):
    return SimpleNamespace(stop_reason=stop, content=list(content))


def test_agent_stages_but_never_applies(store):
    fake = FakeClaude(
        reply("tool_use", tool_use("t1", "search_products", query="spaghetti")),
        reply("tool_use", tool_use("t2", "create_deal", product_id="barilla-spaghetti", type="amount_off",
                                   value=1, ends_at=None, pairs_with=["rao-marinara"])),
        reply("end_turn", text("I staged Spaghetti $1 off. Press Confirm to make it live.")),
    )
    agent = MerchantAgent(store, client=fake)
    out = agent.chat("spaghetti $1 off")
    assert out["reply"].startswith("I staged Spaghetti $1 off")
    assert [c["tool"] for c in out["staged"]] == ["create_deal"]
    assert product(store, "barilla-spaghetti")["deal_id"] is None   # still not live
    roles = [m["role"] for m in agent.messages]
    assert roles == ["user", "system", "assistant", "user", "assistant", "user", "assistant"]
    first = fake.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["betas"] == ["server-side-fallback-2026-07-01"]
    assert all(t["strict"] for t in first["tools"])
    assert "barilla-spaghetti" in agent.messages[3]["content"][0]["content"]   # search result went back


def test_tool_errors_go_back_to_claude(store):
    fake = FakeClaude(
        reply("tool_use", tool_use("t1", "update_price", product_id="ghost", new_price=1)),
        reply("end_turn", text("Which product did you mean?")),
    )
    agent = MerchantAgent(store, client=fake)
    agent.chat("make ghost $1")
    result = agent.messages[3]["content"][0]
    assert result["is_error"] and "No product" in result["content"]


def test_console_notes_reach_the_next_turn(store, tools):
    fake = FakeClaude(reply("end_turn", text("ok")), reply("end_turn", text("ok")))
    agent = MerchantAgent(store, client=fake)
    agent.chat("hi")
    agent.note("The owner CONFIRMED change #1")
    agent.chat("thanks")
    system_msg = fake.calls[1]["messages"][-1]
    assert system_msg["role"] == "system" and "CONFIRMED change #1" in system_msg["content"]
    # the live catalog rides along each turn, so Claude can stage without a search round
    assert "kirkland-parmesan | Parmesan (" in system_msg["content"] and "$3 off → $9.99" in system_msg["content"]
    assert agent.notes == []


def test_refusal_keeps_history_valid(store):
    fake = FakeClaude(reply("refusal"), reply("end_turn", text("ok")))
    agent = MerchantAgent(store, client=fake)
    assert "can't help" in agent.chat("something odd")["reply"]
    agent.chat("never mind")
    roles = [m["role"] for m in fake.calls[1]["messages"]]
    assert roles == ["user", "system", "assistant", "user", "system"]


def test_api_error_rolls_back_the_turn(store):
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    fake = FakeClaude(err, reply("end_turn", text("ok")))
    agent = MerchantAgent(store, client=fake)
    out = agent.chat("hello")
    assert out["error"] and agent.messages == []
    agent.chat("hello again")
    assert [m["role"] for m in fake.calls[1]["messages"]] == ["user", "system"]


# ── Console API ──

def test_console_confirm_flow(store, tools):
    fake = FakeClaude(
        reply("tool_use", tool_use("t1", "set_stock", product_id="rao-marinara", stock=0)),
        reply("end_turn", text("Staged: Rao's out of stock.")),
    )
    agent = MerchantAgent(store, client=fake)
    api = TestClient(create_app(store, agent))
    res = api.post("/api/chat", json={"message": "we're out of Rao's"}).json()
    cid = res["staged"][0]["id"]
    assert api.post(f"/api/changes/{cid}/confirm").json()["status"] == "applied"
    assert api.post(f"/api/changes/{cid}/confirm").status_code == 409
    state = api.get("/api/state").json()
    rao = next(p for p in state["catalog"] if p["id"] == "rao-marinara")
    assert rao["stock"] == 0 and state["changes"][0]["status"] == "applied"
    assert api.post(f"/api/changes/{cid}/undo").json()["tool"] == "undo"
    assert any("undid change" in n for n in agent.notes)
    assert api.get("/").status_code == 200


def test_missing_credentials_is_a_friendly_reply(store):
    class NoAuth(FakeClaude):
        def create(self, **kw):
            raise TypeError('"Could not resolve authentication method. Expected one of api_key, ..."')
    agent = MerchantAgent(store, client=NoAuth())
    out = agent.chat("hello")
    assert out["error"] and "ANTHROPIC_API_KEY" in out["reply"] and agent.messages == []


def test_owner_deal_replaces_the_suggestion_on_the_cart(store, tools):
    """The merchant demo moment, through merchant_apply: the cart switches to the new deal."""
    store.q("update deals set active = false where id = 'd-parm-3off'")
    add_to_cart(store, "barilla-spaghetti")
    assert cart(store)["suggestion"]["product_id"] == "french-baguette"
    ch = stage(tools, "create_deal", product_id="kirkland-parmesan", type="amount_off", value=3,
               ends_at=None, pairs_with=["barilla-spaghetti"])
    store.apply(ch["id"])
    assert cart(store)["suggestion"]["text"] == "Parmesan is $3 off in Aisle 4. Want it?"


def test_replacing_the_deal_on_screen_shows_the_new_one(store, tools):
    """Ending the old deal re-offers another one in the same transaction; the new deal must still win."""
    add_to_cart(store, "barilla-spaghetti")
    assert cart(store)["suggestion"]["deal_id"] == "d-parm-3off"
    ch = stage(tools, "create_deal", product_id="kirkland-parmesan", type="amount_off", value=4,
               ends_at=None, pairs_with=["barilla-spaghetti"])
    store.apply(ch["id"])
    assert cart(store)["suggestion"]["text"] == "Parmesan is $4 off in Aisle 4. Want it?"


def test_insights_tool_and_state(store, tools):
    add_to_cart(store, "barilla-spaghetti")            # the cart offers Parmesan
    data = json.loads(tools.run("store_insights", {}, "how are deals doing")[0])
    parm = next(d for d in data["deals"] if d["deal_id"] == "d-parm-3off")
    assert parm["offered"] >= 1 and "avg_basket" in data["store"]
    api = TestClient(create_app(store, MerchantAgent(store, client=FakeClaude())))
    state = api.get("/api/state").json()
    assert "deals_offered" in state["insights"] and state["deal_performance"]
