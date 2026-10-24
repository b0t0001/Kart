"""Member memory (CONTRACT v0.14, BETA): feature member_memory, off by default."""

from __future__ import annotations

from datetime import date, timedelta

import psycopg
import pytest

import kartdb
from test_cart import add

TZ = "America/Los_Angeles"


def store_today(conn) -> date:
    return conn.execute(f"select (now() at time zone '{TZ}')::date").fetchone()[0]


@pytest.fixture
def member_cart(cart, conn):
    """Cart 7 with the beta on for this cart only; test members are wiped first."""
    conn.execute("delete from members where member_id like 'it-%'")
    cart("set_feature", p_feature="member_memory", p_on=True)
    return cart


# ── Off (the default) ──

def test_flag_seeded_off_and_set_member_refuses(cart, conn):
    assert conn.execute("select enabled_default from feature_flags where name = 'member_memory'").fetchone()[0] is False
    with pytest.raises(psycopg.errors.RaiseException, match="feature_off: member_memory"):
        cart("set_member", p_member_id="it-1")
    with pytest.raises(psycopg.errors.RaiseException, match="feature_off: member_memory"):
        cart("set_demo_date", p_date="2026-10-30")
    row = cart("reset_cart")
    assert row["member_id"] is None and row["demo_date"] is None and row["member_rev"] == 0


# ── Sign-in ──

def test_set_member_creates_unknown_member(member_cart, conn):
    row = member_cart("set_member", p_member_id="it-1")
    assert row["member_id"] == "it-1"
    assert conn.execute("select name from members where member_id = 'it-1'").fetchone() == (None,)


def test_bad_member_id_rejected(member_cart):
    with pytest.raises(psycopg.errors.RaiseException, match="bad member id"):
        member_cart("set_member", p_member_id="it 1; drop")


def test_set_member_null_signs_out(member_cart):
    member_cart("set_member", p_member_id="it-1")
    assert member_cart("set_member", p_member_id=None)["member_id"] is None


def test_new_trip_clears_member_keeps_demo_date(member_cart):
    member_cart("set_member", p_member_id="it-1")
    member_cart("set_demo_date", p_date="2026-10-30")
    row = member_cart("reset_cart")
    assert row["member_id"] is None
    assert row["demo_date"] == "2026-10-30"


# ── Checkout feeds history ──

def purchases(conn, member_id):
    return conn.execute(
        f"select product_id, qty, source, (bought_at at time zone '{TZ}')::date from member_purchases "
        "where member_id = %s order by product_id", [member_id]).fetchall()


def test_checkout_copies_purchases_once_with_demo_date(member_cart, conn):
    today = store_today(conn)
    member_cart("set_member", p_member_id="it-1")
    add(member_cart, "barilla-spaghetti")
    add(member_cart, "barilla-spaghetti")
    add(member_cart, "whole-milk")
    member_cart("set_demo_date", p_date=(today + timedelta(days=6)).isoformat())
    receipt = member_cart("checkout")
    member_cart("checkout")                                   # idempotent per trip
    later = today + timedelta(days=6)
    assert purchases(conn, "it-1") == [("barilla-spaghetti", 2, "checkout", later), ("whole-milk", 1, "checkout", later)]
    stored = conn.execute(f"select member_id, (created_at at time zone '{TZ}')::date from receipts where id = %s",
                          [receipt["id"]]).fetchone()
    assert stored == ("it-1", today)                          # the receipt itself stays real


def test_guest_checkout_writes_no_purchases(member_cart, conn):
    add(member_cart, "whole-milk")
    receipt = member_cart("checkout")
    assert conn.execute("select count(*) from member_purchases").fetchone()[0] == 0
    assert conn.execute("select member_id from receipts where id = %s", [receipt["id"]]).fetchone() == (None,)


# ── member_profile: "this week" (§4) ──

TODAY = date(2026, 10, 24)                                    # a Saturday


@pytest.fixture
def member(conn):
    conn.execute("delete from members where member_id like 'it-%'")
    conn.execute("insert into members (member_id, name, household) values ('it-p', 'Dylan', 4)")
    return "it-p"


def buy(conn, member_id, product_id, days_ago, qty=1, today=TODAY):
    """A purchase at noon store time, days_ago days before today (negative = in the future)."""
    conn.execute(
        f"insert into member_purchases (member_id, product_id, qty, price, bought_at, source) "
        f"values (%s, %s, %s, 1.00, ((%s::date - %s) + time '12:00') at time zone '{TZ}', 'seed')",
        [member_id, product_id, qty, today, days_ago])


def memory(conn, member_id, kind, text, days=None, items=None, today=TODAY):
    import json
    row = conn.execute(
        "insert into member_memories (member_id, kind, text, event_date, items) values (%s, %s, %s, %s, %s::jsonb) "
        "returning id",
        [member_id, kind, text, None if days is None else today + timedelta(days=days),
         None if items is None else json.dumps(items)]).fetchone()
    return row[0]


def profile(conn, member_id, today=TODAY, cart_id=None):
    return conn.execute("select member_profile(%s, %s, %s)", [member_id, cart_id, today]).fetchone()[0]


def picks(prof):
    return [(p["product_id"], p["kind"], p["reason"]) for p in prof["picks"]]


def test_due_pick_weekly_milk(conn, member):
    for days in (7, 14, 21, 28):
        buy(conn, member, "whole-milk", days)
    assert ("whole-milk", "due", "every week · last Sat") in picks(profile(conn, member))


def test_usual_pick_on_weekday(conn, member):
    for days in (7, 14, 21, 3):                               # three Saturdays, and last Wednesday
        buy(conn, member, "mission-tortillas", days)
    assert picks(profile(conn, member)) == [("mission-tortillas", "usual", "your Saturday usual")]


def test_event_pick(conn, member):
    mid = memory(conn, member, "event", "Leo's soccer party, nachos for the team", days=1,
                 items=[{"product_id": "tostitos-chips", "qty": 1}, {"product_id": "tostitos-salsa", "qty": 1}])
    first = profile(conn, member)["picks"][0]
    assert (first["product_id"], first["kind"], first["reason"], first["memory_id"]) == \
        ("tostitos-salsa", "event", "Leo's soccer party · tomorrow", mid)    # chips: the deal card's job


def test_live_deal_products_never_picked(conn, member):
    for days in (7, 14, 21, 28):
        buy(conn, member, "tostitos-chips", days)
    assert "tostitos-chips" not in [p for p, _, _ in picks(profile(conn, member))]
    conn.execute("update deals set active = false where id = 'd-chips-150off'")
    assert "tostitos-chips" in [p for p, _, _ in picks(profile(conn, member))]


def test_mix_one_per_signal_then_cap_3(conn, member):
    memory(conn, member, "event", "Leo's soccer party", days=1, items=[{"product_id": "tostitos-salsa", "qty": 1}])
    for days in (7, 14, 21, 28):
        buy(conn, member, "whole-milk", days)
    for days in (10, 20, 30):
        buy(conn, member, "large-eggs", days)
    for days in (7, 14, 21, 3):
        buy(conn, member, "mission-tortillas", days)
    prof = profile(conn, member)
    assert [(p["product_id"], p["kind"]) for p in prof["picks"]] == \
        [("tostitos-salsa", "event"), ("whole-milk", "due"), ("mission-tortillas", "usual")]


def test_picks_skip_plan_and_cart_and_out_of_stock(cart, conn, member):
    for pid in ("whole-milk", "large-eggs", "bananas"):
        for days in (7, 14, 21, 28):
            buy(conn, member, pid, days)
    cart("set_plan", p_plan=[{"product_id": "whole-milk", "reason": "milk"}])
    add(cart, "large-eggs")
    conn.execute("update products set stock = 0 where id = 'bananas'")
    assert picks(profile(conn, member, cart_id="7")) == []


def test_today_uses_store_timezone(conn, member):
    conn.execute("insert into member_purchases (member_id, product_id, qty, price, bought_at, source) "
                 "values (%s, 'whole-milk', 1, 5.49, '2026-10-25 01:30+00', 'seed')", [member])   # Sat 6:30 pm PDT
    prof = profile(conn, member)
    assert prof["last_trip"]["date"] == "2026-10-24" and prof["member"]["trips"] == 1


def test_future_purchases_ignored(conn, member):
    buy(conn, member, "whole-milk", 7)
    buy(conn, member, "whole-milk", -3)
    prof = profile(conn, member)
    assert prof["member"]["trips"] == 1 and prof["last_trip"]["date"] == "2026-10-17"


def test_demo_date_moves_today(member_cart, conn, member):
    memory(conn, member, "event", "Friendsgiving for 10", days=7)
    member_cart("set_demo_date", p_date="2026-10-30")
    prof = conn.execute("select member_profile(%s, '7')", [member]).fetchone()[0]
    assert (prof["today"], prof["weekday"]) == ("2026-10-30", "Friday")
    assert prof["memories"][0]["days_until"] == 1


def test_recent_past_event_listed_first(conn, member):
    memory(conn, member, "preference", "Likes the Marinara here")
    memory(conn, member, "event", "Leo's soccer party", days=-2)
    mems = profile(conn, member)["memories"]
    assert [(m["kind"], m["days_until"]) for m in mems] == [("event", -2), ("preference", None)]


def test_profile_shape_usuals_and_last_trip(conn, member):
    for days in (7, 14, 21, 28):
        buy(conn, member, "whole-milk", days)
    buy(conn, member, "tostitos-salsa", 7, qty=2)
    prof = profile(conn, member)
    assert prof["member"] == {"member_id": "it-p", "name": "Dylan", "household": 4,
                              "since": prof["member"]["since"], "trips": 4}
    assert prof["usuals"][0] == {"product_id": "whole-milk", "short_name": "Milk", "times": 4, "every_days": 7,
                                 "last": "2026-10-17", "weekday": "Saturday"}
    assert prof["last_trip"] == {"date": "2026-10-17", "items": ["Milk", "Salsa"], "total": 3.0}


def test_unknown_member_is_null(conn):
    assert profile(conn, "it-nobody") is None


# ── Remember, save for later, forget ──

def rpc(conn, fn, **params):
    return kartdb.rpc(conn, fn, **params)


def test_remember_event_then_profile_lists_it(conn, member):
    saved = rpc(conn, "member_remember", p_member_id=member, p_kind="event", p_text="Friendsgiving for 10",
                p_event_date="2026-10-31")
    assert {k: saved[k] for k in ("kind", "text", "event_date")} == \
        {"kind": "event", "text": "Friendsgiving for 10", "event_date": "2026-10-31"}
    mems = profile(conn, member)["memories"]
    assert (mems[0]["id"], mems[0]["days_until"]) == (saved["id"], 7)


def test_remember_name_and_household_update_member(conn, member):
    assert rpc(conn, "member_remember", p_member_id=member, p_kind="name", p_text="  Dyl  ") == \
        {"kind": "name", "text": "Dyl"}
    rpc(conn, "member_remember", p_member_id=member, p_kind="household", p_text="5")
    assert conn.execute("select name, household from members where member_id = %s", [member]).fetchone() == ("Dyl", 5)
    with pytest.raises(psycopg.errors.RaiseException, match="household"):
        rpc(conn, "member_remember", p_member_id=member, p_kind="household", p_text="a few")
    with pytest.raises(psycopg.errors.RaiseException, match="bad kind"):
        rpc(conn, "member_remember", p_member_id=member, p_kind="secret", p_text="x")
    with pytest.raises(psycopg.errors.RaiseException, match="unknown member"):
        rpc(conn, "member_remember", p_member_id="it-nobody", p_kind="note", p_text="x")


def test_reminder_requires_date(conn, member):
    with pytest.raises(psycopg.errors.RaiseException, match="needs a date"):
        rpc(conn, "member_remember", p_member_id=member, p_kind="reminder", p_text="batteries")


def test_save_for_later_merges_and_rejects_unknown(conn, member):
    mid = memory(conn, member, "event", "Friendsgiving for 10", days=7)
    rpc(conn, "member_save_for_later", p_member_id=member, p_memory_id=mid,
        p_items=[{"product_id": "barilla-spaghetti", "qty": 2}, {"product_id": "rao-marinara", "qty": 1}])
    saved = rpc(conn, "member_save_for_later", p_member_id=member, p_memory_id=mid,
                p_items=[{"product_id": "rao-marinara", "qty": 3}])
    assert [(i["product_id"], i["short_name"], i["qty"]) for i in saved["items"]] == \
        [("barilla-spaghetti", "Spaghetti", 2), ("rao-marinara", "Marinara", 3)]
    with pytest.raises(psycopg.errors.RaiseException, match="unknown product: turkey"):
        rpc(conn, "member_save_for_later", p_member_id=member, p_memory_id=mid, p_items=[{"product_id": "turkey"}])
    pref = memory(conn, member, "preference", "Likes the Marinara here")
    with pytest.raises(psycopg.errors.RaiseException, match="not an event"):
        rpc(conn, "member_save_for_later", p_member_id=member, p_memory_id=pref,
            p_items=[{"product_id": "rao-marinara", "qty": 1}])


def test_save_for_later_rejects_other_members_memory(conn, member):
    conn.execute("insert into members (member_id) values ('it-other')")
    theirs = memory(conn, "it-other", "event", "Their party", days=3)
    with pytest.raises(psycopg.errors.RaiseException, match="not your memory"):
        rpc(conn, "member_save_for_later", p_member_id=member, p_memory_id=theirs,
            p_items=[{"product_id": "rao-marinara", "qty": 1}])


def test_forget_one(conn, member):
    mid = memory(conn, member, "note", "Gluten-free dinner guests")
    assert rpc(conn, "member_forget", p_member_id=member, p_memory_id=mid) == {"forgotten": 1}
    assert rpc(conn, "member_forget", p_member_id=member, p_memory_id=mid) == {"forgotten": 0}
    assert profile(conn, member)["memories"] == []


def test_forget_all_signs_cart_out(member_cart, conn):
    member_cart("set_member", p_member_id="it-1")
    add(member_cart, "whole-milk")
    member_cart("checkout")
    assert rpc(conn, "member_forget", p_member_id="it-1") == {"forgotten": "all"}
    assert conn.execute("select count(*) from member_purchases where member_id = 'it-1'").fetchone()[0] == 0
    assert conn.execute("select member_id from carts where cart_id = '7'").fetchone() == (None,)
    assert profile(conn, "it-1") is None


def test_writes_bump_member_rev(member_cart, conn):
    member_cart("set_member", p_member_id="it-1")
    rev = lambda: conn.execute("select member_rev from carts where cart_id = '7'").fetchone()[0]
    start = rev()
    saved = rpc(conn, "member_remember", p_member_id="it-1", p_kind="event", p_text="Party", p_event_date="2026-11-01")
    rpc(conn, "member_save_for_later", p_member_id="it-1", p_memory_id=saved["id"],
        p_items=[{"product_id": "tostitos-salsa", "qty": 1}])
    rpc(conn, "member_forget", p_member_id="it-1", p_memory_id=saved["id"])
    assert rev() == start + 3


# ── The demo seed ──

def test_seed_member_makes_the_demo_profile(conn, member):
    """Default (the demo): ten weeks of history and no party; Dylan tells Kart about Leo's party live in Act 1."""
    import members as members_cli
    first = members_cli.seed_member(conn, "it-seed", "Dylan", 4, TODAY)
    prof = profile(conn, "it-seed")
    assert prof["member"]["name"] == "Dylan" and prof["member"]["household"] == 4
    assert prof["member"]["trips"] >= 15
    assert picks(prof)[:2] == [("whole-milk", "due", "every week · last Sat"),
                               ("mission-tortillas", "usual", "your Saturday usual")]
    assert [m["text"] for m in prof["memories"]] == ["Likes the Marinara here"]
    assert first["event_date"] is None
    assert members_cli.seed_member(conn, "it-seed", "Dylan", 4, TODAY) == first          # re-runnable


def test_seed_with_party_for_rehearsals(conn, member):
    import members as members_cli
    made = members_cli.seed_member(conn, "it-seed", "Dylan", 4, TODAY, with_party=True)
    party = profile(conn, "it-seed")["memories"][0]
    assert made["event_date"] == "2026-10-31"                 # "next Saturday" from Saturday the 24th
    assert (party["text"], party["event_date"]) == ("Leo's soccer team party, pasta for 12", "2026-10-31")
    assert [(i["product_id"], i["qty"]) for i in party["items"]] == [("barilla-spaghetti", 3), ("rao-marinara", 2)]


# ── Edge cases (§3.9) ──

def test_lookup_known_unknown_never_creates(conn, member):
    assert conn.execute("select member_lookup(%s)", [member]).fetchone()[0] == {"exists": True, "name": "Dylan"}
    assert conn.execute("select member_lookup('it-zzz')").fetchone()[0] == {"exists": False, "name": None}
    assert conn.execute("select count(*) from members where member_id = 'it-zzz'").fetchone()[0] == 0


def test_sensitive_lines_not_stored(member_cart, conn):
    conn.execute("update products set category = 'pharmacy' where id = 'bananas'")
    member_cart("set_member", p_member_id="it-1")
    add(member_cart, "bananas")
    add(member_cart, "whole-milk")
    member_cart("checkout")
    assert [r[0] for r in purchases(conn, "it-1")] == ["whole-milk"]


def test_sensitive_products_hidden_from_profile(conn, member):
    for days in (7, 14, 21, 28):
        buy(conn, member, "bananas", days)
        buy(conn, member, "whole-milk", days)
    conn.execute("update products set category = 'pregnancy' where id = 'bananas'")
    prof = profile(conn, member)
    seen = [p["product_id"] for p in prof["picks"]] + [u["product_id"] for u in prof["usuals"]]
    assert "bananas" not in seen and "whole-milk" in seen
    assert prof["last_trip"]["items"] == ["Milk"]


def test_undated_event_expires_after_30_days(conn, member):
    fresh = memory(conn, member, "event", "Game night sometime")
    stale = memory(conn, member, "event", "Housewarming someday")
    conn.execute("update member_memories set created_at = now() - interval '10 days' where id = %s", [fresh])
    conn.execute("update member_memories set created_at = now() - interval '40 days' where id = %s", [stale])
    memory(conn, member, "preference", "Likes the Marinara here")
    mems = profile(conn, member, today=None)["memories"]
    assert [(m["text"], m["upcoming"]) for m in mems] == [
        ("Game night sometime", True), ("Likes the Marinara here", False), ("Housewarming someday", False)]


def test_seed_prints_what_it_made(db_url, monkeypatch, capsys):
    import sys
    import members as members_cli
    monkeypatch.setenv("KART_ENV_FILE", "/dev/null")
    argv = ["members.py", "seed", "--member", "it-cli", "--today", "2026-10-24", "--db-url", db_url]
    monkeypatch.setattr(sys, "argv", argv)
    members_cli.main()
    assert "No party yet: Dylan tells Kart about it in Act 1" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", argv + ["--with-party"])
    members_cli.main()
    assert "Leo's soccer team party: 2026-10-31 (next Saturday)" in capsys.readouterr().out


def test_fill_skips_more_items_of_a_saved_list(conn, member):
    """The event's list is one line on the card ("Shop it"); open slots go to other signals, not its second item."""
    memory(conn, member, "event", "Leo's soccer team party", days=1,
           items=[{"product_id": "barilla-spaghetti", "qty": 3}, {"product_id": "rao-marinara", "qty": 2}])
    for days in (7, 14, 21, 28):
        buy(conn, member, "whole-milk", days)
    for days in (6, 13, 20, 27):
        buy(conn, member, "large-eggs", days)
    assert [p for p, _, _ in picks(profile(conn, member))] == ["barilla-spaghetti", "whole-milk", "large-eggs"]
