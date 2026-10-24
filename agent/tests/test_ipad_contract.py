"""The iPad sends these exact metadata shapes (ios/KartCore/Sources/KartCore/Voice/LineVoiceSession.swift, LineCodec.metadata)."""

from kart_agent.lines import proactive_line

from fakes import CATALOG

IPAD = {
    "trip_context": {"type": "trip_context", "cart_id": "7", "trip_id": "6f9619ff-8b86-d011-b42d-00c04fc964ff"},
    "trip_context_member": {"type": "trip_context", "cart_id": "7", "trip_id": "6f9619ff-8b86-d011-b42d-00c04fc964ff",
                            "member_id": "1029"},
    "lull": {"type": "lull"},
    "member_forgotten": {"type": "member_forgotten"},
    "member_idle": {"type": "member_idle"},
    "member_forget_failed": {"type": "member_forget_failed"},
    "added": {"type": "cart_changed", "change": "added", "product_id": "rao-marinara"},
    "removed": {"type": "cart_changed", "change": "removed", "product_id": "barilla-spaghetti"},
    "price_dropped": {"type": "cart_changed", "change": "price_dropped", "product_id": "kirkland-parmesan",
                      "from_price": "12.99", "to_price": "9.99"},
    "suggestion": {"type": "suggestion", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan",
                   "text": "Parmesan is $3 off in Aisle 4. Want it?"},
    "deal_changed": {"type": "deal_changed", "deal_id": "d-parm-3off", "product_id": "kirkland-parmesan", "label": "$3 off"},
    "card_response": {"type": "card_response", "card_id": "deal-d-parm-3off", "action": "yes"},
    "ui_action": {"type": "ui_action", "action": "checkout_tapped"},
    "nudge": {"type": "nudge", "product_id": "ground-beef", "kind": "over", "have": 2, "need": 1,
              "text": "That's your 2nd Ground Beef. Your list says 1. Keep it?"},
}


def test_every_ipad_event_is_understood():
    plan = [{"product_id": "rao-marinara"}]
    said = {name: proactive_line(meta, CATALOG, plan) for name, meta in IPAD.items()}
    assert said == {
        "trip_context": None,
        "trip_context_member": None,
        "lull": None,
        "member_forgotten": None,
        "member_idle": None,
        "member_forget_failed": None,
        "added": "Got the Rao's Sauce.",
        "removed": "Took the Spaghetti off your bill.",
        "price_dropped": "Good news, Parmesan just dropped to $9.99.",
        "suggestion": "Parmesan is $3 off in Aisle 4. Want it?",
        "deal_changed": "Heads up, Parmesan just went $3 off.",
        "card_response": None,
        "ui_action": None,
        "nudge": "That's your 2nd Ground Beef. Your list says 1. Keep it?",
    }
