from kart_agent.lines import proactive_line

from fakes import CATALOG

PLAN = [{"product_id": "barilla-spaghetti"}, {"product_id": "rao-marinara"}]


def test_planned_item_added():
    assert proactive_line({"type": "cart_changed", "change": "added", "product_id": "rao-marinara"}, CATALOG, PLAN) == "Got the Rao's Sauce."


def test_unplanned_item_added_is_quiet():
    assert proactive_line({"type": "cart_changed", "change": "added", "product_id": "bananas"}, CATALOG, PLAN) is None


def test_removed_item():
    assert proactive_line({"type": "cart_changed", "change": "removed", "product_id": "barilla-spaghetti"}, CATALOG, PLAN) \
        == "Took the Spaghetti off your bill."


def test_price_drop():
    assert proactive_line({"type": "cart_changed", "change": "price_dropped", "product_id": "kirkland-parmesan",
                           "to_price": "9.99"}, CATALOG, PLAN) == "Good news, Parmesan just dropped to $9.99."


def test_suggestion_speaks_backend_text():
    text = "Parmesan is $3 off in Aisle 4. Want it?"
    assert proactive_line({"type": "suggestion", "deal_id": "d-parm-3off", "text": text}, CATALOG, PLAN) == text


def test_deal_changed():
    assert proactive_line({"type": "deal_changed", "product_id": "kirkland-parmesan", "label": "$3 off"}, CATALOG, PLAN) \
        == "Heads up, Parmesan just went $3 off."


def test_state_events_are_silent():
    for event in ({"type": "trip_context", "cart_id": "7", "trip_id": "t"}, {"type": "card_response"}, {"type": "ui_action"}):
        assert proactive_line(event, CATALOG, PLAN) is None
