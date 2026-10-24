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


def test_short_spoken_answers_to_a_deal():
    from kart_agent.lines import yes_or_no
    for text in ["Yes.", "Yeah, sure.", "Okay!", "Yes please", "Sounds good", "Sure, add it",
                 "Uh, yeah, sure.", "Um, yes, I want the sour cream deal.", "Oh yeah add the sour cream"]:
        assert yes_or_no(text) == "yes", text
    for text in ["No.", "No thanks.", "Nah", "Nope, I'm good", "Not today", "Um, no thanks."]:
        assert yes_or_no(text) == "no", text
    for text in ["", "Yes, but how big is the parmesan?", "What aisle is the salsa in?", "Maybe later",
                 "Yeah, how much is it", "Uh", "Yes, and can you also find me some limes for the tacos tonight"]:
        assert yes_or_no(text) is None, text



def test_an_added_item_counts_toward_its_amount():
    from kart_agent.lines import proactive_line
    from fakes import CATALOG
    plan = [{"product_id": "barilla-spaghetti", "qty": 2}]
    added = {"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"}
    assert proactive_line(added, CATALOG, plan, items=[{"product_id": "barilla-spaghetti", "qty": 1}]) == "Got one Spaghetti, one more to go."
    assert proactive_line(added, CATALOG, plan, items=[{"product_id": "barilla-spaghetti", "qty": 2}]) == "Got the Spaghetti."


def test_kart_says_a_nudge_in_words_not_digits():
    from kart_agent.lines import proactive_line
    from fakes import CATALOG
    plan = [{"product_id": "barilla-spaghetti", "qty": 1, "reason": "noodles"}]     # a line's reason isn't the meal
    over = {"type": "nudge", "product_id": "barilla-spaghetti", "kind": "over", "have": 3, "need": 1,
            "text": "That's 3 Spaghetti in the cart, and your list needs 1. Keep the extra 2?"}
    under = {"type": "nudge", "product_id": "kirkland-parmesan", "kind": "under", "have": 0, "need": 2,
             "text": "Before you go: 2 Parmesan short."}
    assert proactive_line(over, CATALOG, plan) == "That's three pounds of spaghetti in the cart, and your list needs one. Keep the extra?"
    assert proactive_line(under, CATALOG, plan, meal="pasta night for 4") == (
        "Before you go: you're two wedges of parmesan short for pasta night for 4. They're in Aisle 4.")
    assert proactive_line({**under, "product_id": "unknown"}, CATALOG, plan) == "Before you go: 2 Parmesan short."


def test_an_extra_beyond_the_list_is_left_to_the_nudge_when_the_beta_is_on():
    from kart_agent.lines import proactive_line
    from fakes import CATALOG
    plan = [{"product_id": "barilla-spaghetti", "qty": 1}]
    added = {"type": "cart_changed", "change": "added", "product_id": "barilla-spaghetti"}
    extra = [{"product_id": "barilla-spaghetti", "qty": 2}]
    assert proactive_line(added, CATALOG, plan, items=extra, nudges=True) is None   # "Keep the extra?" comes next
    assert proactive_line(added, CATALOG, plan, items=extra) == "Got the Spaghetti."  # beta off: as before



def test_the_combined_checkout_nudge_is_said_as_one_list():
    from kart_agent.lines import proactive_line
    from fakes import CATALOG
    combined = {"type": "nudge", "product_id": "barilla-spaghetti", "kind": "under", "have": 0, "need": 1,
                "text": "Before you go: you still need Spaghetti and Parmesan.",
                "items": [{"product_id": "barilla-spaghetti", "have": 0, "need": 1, "aisle": "Aisle 6"},
                          {"product_id": "kirkland-parmesan", "have": 0, "need": 2, "aisle": "Aisle 4"}]}
    assert proactive_line(combined, CATALOG, [], meal="pasta night for 4") == (
        "Before you go: you still need one pound of spaghetti and two wedges of parmesan for pasta night for 4.")
