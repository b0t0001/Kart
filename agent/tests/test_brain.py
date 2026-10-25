from kart_agent.brain import Brain

from fakes import CATALOG, FakeBackend, FakeLLM, ToolUse, Turn


async def collect(stream):
    return [chunk async for chunk in stream]


async def test_streams_text_and_runs_tools_between_turns():
    backend = FakeBackend()
    llm = FakeLLM([
        Turn(chunks=["Love it. "], tools=[ToolUse("t1", "set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta dinner"}]})]),
        Turn(chunks=["Spaghetti's first, ", "aisle 6."]),
    ])
    brain = Brain(llm=llm)
    chunks = await collect(brain.respond("pasta dinner for four", {"backend": backend, "cart_id": "7", "trip_id": "trip-1"}))
    assert chunks == ["Love it. ", "Spaghetti's first, ", "aisle 6."]
    assert backend.calls[0][0] == "set_plan"
    second = llm.requests[1]["messages"]
    assert second[-1]["role"] == "user" and second[-1]["content"][0]["type"] == "tool_result"
    assert second[-1]["content"][0]["tool_use_id"] == "t1"


async def test_history_carries_across_turns():
    llm = FakeLLM([Turn(chunks=["Hi!"]), Turn(chunks=["Sure."])])
    brain = Brain(llm=llm)
    ctx = {"backend": FakeBackend(), "cart_id": "7", "trip_id": "trip-1"}
    await collect(brain.respond("hello", ctx))
    await collect(brain.respond("thanks", ctx))
    roles = [m["role"] for m in llm.requests[1]["messages"]]
    assert roles == ["user", "assistant", "user"]


async def test_system_prompt_forbids_invented_prices():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "Never invent" in system and "two short sentences" in system


async def test_system_prompt_plans_the_basics_and_leaves_extras_to_deal_cards():
    # The backend never offers a deal on something already on the list (02_cart.sql), so a plan that
    # already holds the Parmesan would swallow the demo's deal card.
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "the basics" in system and "deal cards" in system


async def test_an_empty_turn_never_leaves_an_empty_assistant_message():
    llm = FakeLLM([Turn(chunks=[]), Turn(chunks=["Sure."])])     # e.g. a refusal: nothing came back
    brain = Brain(llm=llm)
    ctx = {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}
    first = await collect(brain.respond("hmm", ctx))
    assert first == ["Sorry, say that again?"]
    await collect(brain.respond("pasta", ctx))
    assert all(m["content"] for m in llm.requests[1]["messages"] if m["role"] == "assistant")


class RefusingLLM:
    """Streams its own apology, then returns no content blocks (what llm.py does on a refusal)."""

    def __init__(self):
        self.requests = []

    async def stream(self, *, system, messages, tools):
        self.requests.append({"messages": list(messages)})
        yield ("text", "Sorry, I can't help with that one.")
        yield ("final", [], "end_turn")


async def test_a_refusal_is_said_once_and_stored_as_said():
    llm = RefusingLLM()
    brain = Brain(llm=llm)
    said = await collect(brain.respond("hmm", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert said == ["Sorry, I can't help with that one."]
    assert brain.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Sorry, I can't help with that one."}]}


async def test_the_store_products_are_in_the_prompt_so_planning_skips_the_search():
    # Each Claude round costs about 1.5 s of voice latency; ids in the prompt let set_plan go first.
    llm = FakeLLM([Turn(chunks=["ok"])])
    brain = Brain(llm=llm)
    brain.set_catalog(CATALOG)
    await collect(brain.respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "- barilla-spaghetti: Spaghetti, Barilla Spaghetti, 1 lb (pasta)" in system   # sizes: amounts count packages
    assert "8.49" not in system                           # prices, deals, stock and aisles change: tools only


async def test_system_prompt_speaks_before_it_looks_things_up():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "One sec" in llm.requests[0]["system"]


async def test_text_from_two_rounds_is_spoken_with_a_space_between():
    llm = FakeLLM([
        Turn(chunks=["Pasta night, nice. One sec."], tools=[ToolUse("t1", "set_plan", {"items": [{"product_id": "barilla-spaghetti", "reason": "pasta"}]})]),
        Turn(chunks=["Your list is ready."]),
    ])
    chunks = await collect(Brain(llm=llm).respond("pasta dinner", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "".join(chunks) == "Pasta night, nice. One sec. Your list is ready."



async def test_system_prompt_asks_for_the_math_behind_each_amount():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "basis" in llm.requests[0]["system"]



async def test_the_demo_meals_have_exact_lists_in_the_prompt():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "barilla-spaghetti x1, rao-marinara x1, french-baguette x1" in system
    assert "tostitos-salsa x1, queso x1, black-beans x1, jalapenos x1, daisy-sour-cream x1. Leave the chips off" in system


async def test_the_prompt_says_how_to_edit_the_list_and_what_to_do_when_the_store_lacks_something():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "say its readback" in system and "change_by" in system and "replaces" in system
    assert "undo_last_edit" in system
    assert "in_cart_not_on_list" in system and "Keep it?" in system
    assert "call not_sold_here" in system and "Never say another store has it" in system


async def test_a_clean_list_edit_is_read_back_word_for_word_without_another_claude_round():
    llm = FakeLLM([Turn(chunks=["Sure."], tools=[ToolUse("t1", "add_to_plan", {"product_id": "daisy-sour-cream",
                                                                               "reason": "tacos"})])])
    brain = Brain(llm=llm)                                    # one scripted turn: a second Claude round would fail
    said = await collect(brain.respond("add sour cream", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "".join(said) == "Sure. Added sour cream, Aisle 8."
    assert brain.messages[-1] == {"role": "assistant", "content": [{"type": "text", "text": "Added sour cream, Aisle 8."}]}


async def test_a_sold_out_edit_goes_back_to_claude_to_offer_a_substitute():
    backend = FakeBackend()
    salsa = next(p for p in backend.catalog if p["id"] == "tostitos-salsa")
    salsa["stock"], salsa["in_stock"] = 0, False
    llm = FakeLLM([Turn(chunks=["Sure."], tools=[ToolUse("t1", "add_to_plan", {"product_id": "tostitos-salsa",
                                                                               "reason": "nachos"})]),
                   Turn(chunks=["Sorry, salsa is sold out today. The queso in Aisle 5 is in stock. Want that instead?"])])
    said = await collect(Brain(llm=llm).respond("add salsa", {"backend": backend, "cart_id": "7", "trip_id": "t"}))
    assert "".join(said).endswith("Want that instead?") and not llm.turns


async def test_no_i_said_x_undoes_the_last_edit_and_makes_the_right_one():
    backend = FakeBackend()
    c = {"backend": backend, "cart_id": "7", "trip_id": "t", "undo": []}
    llm = FakeLLM([Turn(chunks=["Sure."], tools=[ToolUse("t1", "add_to_plan", {"product_id": "daisy-sour-cream",
                                                                               "reason": "tacos"})]),
                   Turn(chunks=["Sorry."], tools=[ToolUse("t2", "undo_last_edit", {}),
                                                  ToolUse("t3", "add_to_plan", {"product_id": "tostitos-salsa",
                                                                                "reason": "tacos"})])])
    brain = Brain(llm=llm)
    await collect(brain.respond("add sour cream", c))
    said = await collect(brain.respond("no, I said salsa", c))
    assert "".join(said) == "Sorry. Took sour cream back off your list. Added salsa, Aisle 5."
    assert [p["product_id"] for p in backend.cart["plan"]] == ["tostitos-salsa"]


async def test_the_prompt_never_lets_kart_imply_a_product_is_safe_for_a_diet():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert "I can't confirm that's gluten-free. Please check the label." in system
    assert "Never promise what the cart will offer later" in system


async def test_several_adds_are_read_back_as_one_line():
    adds = [ToolUse(f"t{i}", "add_to_plan", {"product_id": pid, "reason": "nachos"})
            for i, pid in enumerate(["tostitos-salsa", "queso", "daisy-sour-cream"])]
    llm = FakeLLM([Turn(chunks=["Sure."], tools=adds)])
    said = await collect(Brain(llm=llm).respond("add salsa, queso and sour cream",
                                                {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "".join(said) == "Sure. Added salsa and queso, Aisle 5, and sour cream, Aisle 8."


async def test_the_prompt_covers_unclear_it_rescaling_and_talking_slower():
    llm = FakeLLM([Turn(chunks=["ok"])])
    await collect(Brain(llm=llm).respond("hi", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    system = llm.requests[0]["system"]
    assert '"Two of what?"' in system and "it's 6 people now" in system
    assert "I can't change how fast I talk" in system


async def test_a_combined_read_back_keeps_the_budget_warning():
    backend = FakeBackend()
    backend.cart.update({"budget": 10, "total": 0})
    backend.cart["plan"] = [{"product_id": "barilla-spaghetti", "reason": "pasta", "qty": 1}]
    adds = [ToolUse(f"t{i}", "add_to_plan", {"product_id": pid, "reason": "pasta"})
            for i, pid in enumerate(["rao-marinara", "tostitos-salsa"])]
    said = await collect(Brain(llm=FakeLLM([Turn(chunks=["Sure."], tools=adds)])).respond(
        "add marinara and salsa", {"backend": backend, "cart_id": "7", "trip_id": "t"}))
    assert "".join(said) == "Sure. Added rao's sauce, Aisle 6, and salsa, Aisle 5. That puts you at $10.48, over your $10."


async def test_kart_acknowledges_once_across_a_lookup():
    # "No problem." before a tool round, then "Okay, I'll skip that one." after it: the second "Okay," goes.
    llm = FakeLLM([Turn(chunks=["No problem."], tools=[ToolUse("t1", "get_cart", {})]),
                   Turn(chunks=["Okay, ", "I'll skip", " that one."])])
    chunks = await collect(Brain(llm=llm).respond("I'm all set", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "".join(chunks) == "No problem. I'll skip that one."


async def test_an_answer_that_only_starts_like_an_acknowledgement_is_kept():
    llm = FakeLLM([Turn(chunks=["One sec."], tools=[ToolUse("t1", "get_cart", {})]),
                   Turn(chunks=["Sure thing: ", "your total is $7.37."])])
    chunks = await collect(Brain(llm=llm).respond("total?", {"backend": FakeBackend(), "cart_id": "7", "trip_id": "t"}))
    assert "".join(chunks) == "One sec. Sure thing: your total is $7.37."


async def test_quiet_after_a_lookup_is_still_never_said():
    llm = FakeLLM([Turn(chunks=["Hm."], tools=[ToolUse("t1", "get_cart", {})]), Turn(chunks=["<quiet>"])])
    chunks = await collect(Brain(llm=llm).respond("(to a friend) grab the car", {"backend": FakeBackend(), "cart_id": "7",
                                                                                  "trip_id": "t"}))
    assert "".join(chunks) == "Hm."
