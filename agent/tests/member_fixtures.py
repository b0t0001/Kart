"""A member profile in the backend's member_profile shape (CONTRACT v0.14), for agent tests."""

PROFILE = {
    "member": {"member_id": "1029", "name": "Dylan", "household": 4, "since": "2026-08-14", "trips": 15},
    "today": "2026-10-24", "weekday": "Saturday",
    "picks": [
        {"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "kind": "event",
         "reason": "Leo's soccer party · tomorrow", "aisle": "Aisle 6", "memory_id": 16},
        {"product_id": "whole-milk", "short_name": "Milk", "kind": "due", "reason": "every week · last Sat",
         "aisle": "Aisle 8"},
    ],
    "usuals": [{"product_id": "whole-milk", "short_name": "Milk", "times": 10, "every_days": 7, "last": "2026-10-17",
                "weekday": "Saturday"}],
    "memories": [
        {"id": 16, "kind": "event", "text": "Leo's soccer party, pasta for the team", "event_date": "2026-10-25",
         "days_until": 1, "upcoming": True,
         "items": [{"product_id": "barilla-spaghetti", "short_name": "Spaghetti", "qty": 1},
                   {"product_id": "rao-marinara", "short_name": "Rao's Sauce", "qty": 1}]},
        {"id": 17, "kind": "preference", "text": "Likes the Marinara here", "event_date": None, "days_until": None,
         "upcoming": False, "items": None},
    ],
    "last_trip": {"date": "2026-10-17", "items": ["Milk", "Tortillas"], "total": 51.2},
}
