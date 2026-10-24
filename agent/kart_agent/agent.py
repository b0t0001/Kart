"""The Line agent: greets, answers the shopper with Claude, and speaks up when the cart or a deal changes."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter
from typing import Any, AsyncIterator

from line.events import AgentSendCustom, AgentSendText, CallEnded, CallStarted, UserCustomSent, UserTurnEnded, UserTurnStarted

from .brain import Brain
from .lines import (DECLINED_LINE, KEEP_LINE, LIST_KEPT, LIST_TOO, NUDGE_OK_LINE, QUIET_OFF_LINE, QUIET_ON_LINE,
                    WELCOME_LINE, accepted_line, nudge_answer, only_ack, only_filler, only_thanks, proactive_line,
                    quiet_request, yes_or_no)
from .memory import (FORGOTTEN_LINE, FORGOTTEN_NOTE, GREETING_TURN, LIST_LATER_LINE, NOT_ME_NOTE, PROFILE_FAILED_LINE,
                     after_last_drop, list_shopped_line, member_section, only_greeting, question, saved_list_offer,
                     still_there_line, welcome_line)
from .tools import run_tool

GREETING = "Hi, I'm Kart. What are we shopping for today?"
_ABOUT_DEALS = re.compile(r"\b(deal|deals|sale|on sale|discount|offer|coupon)\b", re.IGNORECASE)
QUIETED = {"suggestion", "nudge", "deal_changed", "cart_changed", "ui_action"}   # unspoken in quiet mode (cards show)
_POINTING = re.compile(r"\b(this|that|these|those)\b|\bis it\b", re.IGNORECASE)   # "how much is this?"
ADD_THEN_DEAL_SECONDS = 3.0                         # a deal this soon after an add says "Got the X." first
SPEAKING_EVENTS = {"suggestion", "nudge", "deal_changed", "cart_changed", "ui_action", "reconnected"}


def _count_word(n: int) -> str:
    return ["zero", "one", "two", "three"][n] if 0 <= n <= 3 else str(n)


def _digest_answer(text: str) -> str | None:
    """"Yes" / "not now" to the deals question or to one deal; None for anything else (Claude hears it)."""
    lowered = text.lower()
    if "not now" in lowered or "later" in lowered:
        return "no"
    return yes_or_no(text)


def _said_key(meta: dict[str, Any]) -> str | None:
    """Deals are offered once per trip and nudges once per product and direction per trip, so these keys are stable."""
    if meta.get("type") == "suggestion" and meta.get("deal_id"):
        return f"suggestion|{meta['deal_id']}"
    if meta.get("type") == "nudge" and meta.get("product_id"):
        return f"nudge|{meta['product_id']}|{meta.get('kind')}"
    return None


class KartAgent:
    """One per call. `run_filter` decides which events start a turn (a new turn cuts off the current one)."""

    def __init__(self, backend: Any, brain: Brain, cart_id: str = "7", coalesce_seconds: float = 0.6,
                 context_wait_seconds: float = 1.0, barge_in: bool = True, digest_delay_seconds: float = 2.5,
                 profile_timeout_seconds: float = 1.0):
        self.backend = backend
        self.brain = brain
        self.cart_id = cart_id                      # the default; the iPad's trip_context names the real one
        self.trip_id: str | None = None
        self.coalesce_seconds = coalesce_seconds    # an "added" line waits this long for a paired suggestion
        self.context_wait_seconds = context_wait_seconds   # how long the greeting waits for the iPad's trip_context
        self.barge_in = barge_in                    # off (KART_BARGE_IN=off) for a loud floor: nothing cuts Kart off
        self.digest_delay_seconds = digest_delay_seconds   # the pause after reading the list before asking about deals
        self._digest: dict[str, Any] | None = None  # "N deals go with your list": asked, then walked one at a time
        self._digest_asked: set[str] = set()       # deals already asked about in a walk-through this trip
        self._digest_due = False                   # a new list's deals question, held while Kart asked its own
        self._context = asyncio.Event()
        self._plan: list[dict[str, Any]] = []
        self._items: list[dict[str, Any]] = []
        self._catalog: list[dict[str, Any]] = []
        self._speaking = False
        self._pending: str | None = None            # a proactive line that arrived while Kart was talking
        self._last_add: tuple[dict[str, Any], float] | None = None   # the latest "added" event, until it's said
        self._undo: list[dict[str, Any]] = []      # earlier lists, newest last: "undo" puts the last one back
        self._list_too: str | None = None         # the product Kart asked "Take it off the list too?" about
        self._latest_added: str | None = None     # the last product into the cart: what "this" means
        self._unknown_open = False                # an "Is this...?" card is on screen
        self._quiet = False                       # "be quiet": Kart only answers; cards still show
        self._offered: list[str] = []             # deals Kart has offered this trip, for "what was that deal?"
        self._budget: float | None = None         # "keep it under $30" (carts.budget), and the bill so far
        self._diet: dict[str, Any] = {}           # "no dairy": the kinds and products the cart offers no deals on
        self._skipped: set[str] = set()           # taken off the list ("we have some at home"): no deals on them
        self._total = 0.0
        self._cart: dict[str, Any] = {}           # the latest cart row, for the live note on each Claude turn
        self._offer: dict[str, Any] | None = None   # the deal Kart just asked about, until it's answered
        self._nudge: dict[str, Any] | None = None   # the quantity nudge Kart just said (v0.12 beta)
        self._last_asked: str | None = None         # "offer" or "nudge": a plain answer goes to the latest question
        self._said: set[str] = set()                # deals and nudges already said this trip (repeats are dropped)
        self._meal: str | None = None               # "taco night for 4", from Claude's set_plan
        self._nudges = False                        # the cart's quantity_nudges beta (carts.features)
        # Member memory beta (CONTRACT v0.14): set only when the iPad's trip_context names a member.
        self.member_id: str | None = None
        self.profile_timeout_seconds = profile_timeout_seconds   # the greeting never waits longer on memory
        self._profile: dict[str, Any] | None = None
        self._profile_tried = False                 # one read per trip (a failed read isn't retried every turn)
        self._asked = False                         # Kart's one question this trip ("Hey Kart" or a lull)
        self._questions = 0                         # which question in the rotation comes next
        self._question: str | None = None           # a lull question still waiting for its answer
        self._list_offer: dict[str, Any] | None = None   # "Want the list you saved?": the memory, until answered
        self._kart_asked = False                    # Kart's last words were a question (a member's "yeah" answers it)

    # Line filters --------------------------------------------------------------------------------

    def run_filter(self, event: Any) -> bool:
        if isinstance(event, (CallStarted, UserTurnEnded, CallEnded)):
            return True
        if isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "trip_context":       # state only: never interrupt Kart for it
                self.cart_id = str(meta.get("cart_id") or self.cart_id)
                if meta.get("trip_id") and meta.get("trip_id") != self.trip_id:   # a new trip starts fresh
                    self._said, self._meal, self._offer, self._nudge = set(), None, None, None
                    self._undo, self._latest_added, self._unknown_open = [], None, False
                    self._quiet, self._offered, self._diet, self._skipped = False, [], {}, set()
                    self._digest, self._digest_asked, self._digest_due = None, set(), False
                    self._profile, self._profile_tried, self._asked, self._question = None, False, False, None
                member = meta.get("member_id") or None
                if member != self.member_id:             # signed in, out ("not me", idle) or switched: drop it all
                    self._drop_member()
                elif member:                             # same member: a memory changed on the screen, reload it
                    self._profile_tried = False
                self.member_id = member
                self.trip_id = meta.get("trip_id") or self.trip_id
                self._context.set()
                return False
            if meta.get("type") == "member_forgotten":  # "Forget me" on the screen: Kart lets go at once
                return bool(self.member_id)
            if meta.get("type") == "member_idle":       # 3 quiet minutes while signed in
                return bool(self.member_id and not self._speaking and not self._quiet)
            if meta.get("type") == "lull":              # the iPad saw a quiet minute: Kart's one question
                return bool(self.member_id and not self._asked and not self._speaking and not self._quiet
                            and not self._offer and not self._nudge and not self._digest and not self._list_too)
            key = _said_key(meta)
            if key in self._said:                        # the same deal or nudge again (a burst, a second screen)
                return False
            if key:
                self._said.add(key)
            if meta.get("type") == "suggestion" and self._avoided(meta.get("product_id")):
                return True                              # off-diet: process dismisses it, nothing read out or offered
            if meta.get("type") == "suggestion" and self._digest:   # mid walk-through: Kart is reading them out
                return False
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                self._last_add = (meta, time.monotonic())   # a paired deal right behind it says "Got the X" first
                self._latest_added = meta.get("product_id")
            if meta.get("type") == "ui_action" and meta.get("action") == "unknown_item":
                self._unknown_open = True
            if meta.get("type") == "card_response" and str(meta.get("card_id", "")).startswith("confirm"):
                self._unknown_open = False
            if meta.get("type") == "suggestion":
                self._offer = meta                       # "Want it?" can now be answered with a plain yes or no
                self._last_asked = "offer"
            elif meta.get("type") == "nudge":
                self._nudge = meta                       # "Keep it?" / "Before you go…" can be answered by voice
                self._last_asked = "nudge"
            elif meta.get("type") == "card_response":    # answered on the screen
                if str(meta.get("card_id", "")).startswith("digest"):
                    return self._digest is not None      # the deals walk-through: Kart says the next one
                if str(meta.get("card_id", "")).startswith("nudge-"):
                    self._nudge = None
                else:
                    self._offer = None
            if meta.get("type") == "suggestion" and meta.get("text"):
                self._remember_offer(meta["text"])
            if meta.get("type") not in SPEAKING_EVENTS or (self._quiet and meta.get("type") in QUIETED):
                return False
            line = proactive_line(meta, self._catalog, self._plan, self._items, self._meal, self._nudges)
            if not line:
                return False
            if self._speaking:                           # never cut Kart off: say it when this turn ends
                self._pending = line
                return False
            return True
        return False

    def cancel_filter(self, event: Any) -> bool:
        return self.barge_in and isinstance(event, UserTurnStarted)   # barge-in

    # Line agent --------------------------------------------------------------------------------

    async def process(self, env: Any, event: Any) -> AsyncIterator[AgentSendText]:
        if isinstance(event, CallStarted):
            try:                                         # the iPad says which cart right after the call starts
                await asyncio.wait_for(self._context.wait(), self.context_wait_seconds)
            except TimeoutError:
                pass
            await self._refresh()
            rejoining = bool(self._plan or self._items)
            if not rejoining and self.member_id:         # a member's trip that already talked: a dropped call
                try:
                    rejoining = bool(await self.backend.get_transcript(self.cart_id, self.trip_id))
                except Exception:
                    pass
            if rejoining:                                # rejoining a trip in progress (app relaunch, reconnect)
                await self._rejoin()
                if self.member_id:                       # no second "Welcome back", but Kart still knows them
                    await self._load_profile()
                return
            if self.member_id:                           # a signed-in member: welcome back, then what Kart remembers
                await self._load_profile()
                if self._profile is None:
                    async for out in self._say([PROFILE_FAILED_LINE], interruptible=False):
                        yield out
                    return
                welcome = welcome_line(self._profile)
                async for out in self._say([welcome], interruptible=False):
                    yield out
                offer = saved_list_offer(self._profile)
                if offer:                                # the event's day is here: offer its saved list, word for word
                    self._list_offer, line = offer
                    self.brain.remember("(The shopper just signed in.)", f"{welcome} {line}")
                    async for out in self._say([line], interruptible=False):
                        yield out
                    return
                cue = GREETING_TURN.format(welcome=welcome)
                async for out in self._say(self.brain.respond(cue, self._ctx()), interruptible=self.barge_in):
                    yield out
                return
            async for out in self._say([GREETING], interruptible=False):   # chatter can't wipe the greeting
                yield out
        elif isinstance(event, UserTurnEnded):
            text = " ".join(part.content for part in event.content if hasattr(part, "content") and part.content).strip()
            if text and self.member_id and not self._asked \
                    and not (self._offer or self._nudge or self._digest or self._list_too) \
                    and only_greeting(text):             # a bare "Hey Kart" (filler for a guest): the trip's one question
                await self._ensure_profile()
                await self._caption("user", text)
                line = self._next_question()
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            if not text or only_filler(text):            # "Um." gets no answer and no caption
                return
            quiet = quiet_request(text)
            nothing_asked = not self._offer and not self._nudge and not self._digest and not self._list_too \
                and not self._list_offer and not (self.member_id and self._kart_asked)   # member beta: Kart's own question
            if quiet or (nothing_asked and only_thanks(text)):   # "Be quiet." / "Thanks!": no Claude round
                await self._caption("user", text)
                if quiet:
                    self._quiet = quiet == "on"
                line = (QUIET_ON_LINE if self._quiet else QUIET_OFF_LINE) if quiet else WELCOME_LINE
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            if nothing_asked and only_ack(text):
                return
            await self._refresh()
            await self._ensure_profile()
            ctx = self._ctx()
            saved = yes_or_no(text) if self._list_offer else None
            if saved:                                    # "Want the list you saved?" "Yes." / "Not today."
                await self._caption("user", text)
                memory, self._list_offer = self._list_offer, None
                line = LIST_LATER_LINE
                if saved == "yes":
                    out = json.loads(await run_tool("shop_saved_list", {"memory_id": memory["id"]}, ctx))
                    line = list_shopped_line(out.get("next_step")) if "error" not in out else "Sorry, I couldn't put it up."
                self.brain.remember(text, line)
                async for out_text in self._say([line], interruptible=False):
                    yield out_text
                return
            if self._list_offer:                         # more than a yes or no: Claude hears what was asked
                self._list_offer = None
                self._question = "Want the list you saved?"
            plain = yes_or_no(text) if self._list_too and self._last_asked == "list_too" else None
            if plain:                                    # "Take it off the list too?" "Yes."
                await self._caption("user", text)
                product_id, self._list_too = self._list_too, None
                line = LIST_KEPT
                if plain == "yes":
                    out = json.loads(await run_tool("remove_from_plan", {"product_id": product_id}, ctx))
                    line = out.get("readback") or line
                self.brain.remember(text, line)
                async for out_text in self._say([line], interruptible=False):
                    yield out_text
                return
            digest_reply = _digest_answer(text) if self._digest and self._last_asked == "digest" else None
            if digest_reply:                             # "yes" / "not now" to the deals walk-through
                await self._caption("user", text)
                async for out in self._digest_step(digest_reply, ctx):
                    yield out
                return
            asked_nudge = self._nudge and (self._last_asked == "nudge" or not self._offer)
            nudge_reply = nudge_answer(text) if asked_nudge else None
            if asked_nudge and nudge_reply is None:      # a plain yes/no answers the nudge's own question
                plain = yes_or_no(text)
                checkout_list = bool(self._nudge.get("items"))
                if plain == "yes":
                    nudge_reply = "keep" if self._nudge.get("kind") == "over" else ("shop" if checkout_list else "ok")
                elif plain == "no":
                    nudge_reply = "skip" if checkout_list else "ok"
            if nudge_reply:                              # "keep it" / "got it": dismiss_nudge, no Claude round
                await self._caption("user", text)
                nudge, self._nudge = self._nudge, None
                if nudge_reply == "ok" and nudge.get("items"):  # "no thanks" to the checkout list: skip them all
                    nudge_reply = "skip"
                await run_tool("dismiss_nudge", {"action": nudge_reply}, ctx)   # shop: the backend goes back to shopping
                line = KEEP_LINE if nudge_reply == "keep" else NUDGE_OK_LINE
                if nudge_reply == "shop":                    # short at checkout: say where to go
                    items = nudge.get("items") if isinstance(nudge.get("items"), list) else []
                    first = items[0].get("aisle") if items else None
                    aisle = first or next((p.get("aisle") for p in self._catalog if p["id"] == nudge.get("product_id")), None)
                    line = (f"Okay, start in {aisle}." if len(items) > 1 else f"Okay, it's in {aisle}.") if aisle \
                        else "Okay, go grab it."
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            answer = yes_or_no(text) if self._offer else None
            if answer:                                   # a plain yes/no to the deal: no Claude round, nothing invented
                await self._caption("user", text)
                offer, self._offer = self._offer, None
                if answer == "yes":
                    await run_tool("add_to_plan", {"product_id": offer.get("product_id"), "reason": "deal"}, ctx)
                    await self._refresh()                # on the list now: its add gets "Got the X."
                    line = accepted_line(self._catalog, offer.get("product_id"))
                else:
                    await run_tool("dismiss_suggestion", {}, ctx)
                    line = DECLINED_LINE
                self.brain.remember(text, line)
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            heard = text
            if self._offer:                              # more than a yes/no: Claude still needs to know what was asked
                heard = f'(Kart just asked: "{self._offer.get("text", "")}") {text}'
                self._offer = None
            elif self._question:                         # the answer to Kart's lull question
                heard = f'(Kart just asked: "{self._question}") {text}'
            elif _POINTING.search(text) and (seen := await self._what_this_is()):
                heard = f"({seen}) {text}"
            elif _ABOUT_DEALS.search(text) and self._offered:
                heard = f"(Deals Kart offered this trip: {' '.join(self._offered)}) {text}"
            self._question = None
            if live := self._live_note():                # the cart right now: "what's my total?" needs no tool round
                heard = f"{live} {heard}"
            said = []
            async for out in self._say(self._caption_first(text, self.brain.respond(heard, ctx)), interruptible=self.barge_in):
                said.append(out.text)
                yield out
            self._meal = ctx.get("meal") or self._meal
            if ctx.get("signed_out"):                    # "that's not me": a guest from here on
                self._drop_member()
                self.member_id = None
                self.brain.remember(NOT_ME_NOTE, "".join(said).strip() or "Okay.")
            elif ctx.get("memory_changed"):              # remember / save_for_later / forget: reload what Kart knows
                await self._load_profile()
            if ctx.get("show_memories"):                 # "what do you know about me?": the memory screen opens
                yield AgentSendCustom(metadata={"type": "show_memories"})
            await self._refresh()                        # Claude's tools may have changed the list
            self._digest_due = self._digest_due or bool(ctx.get("planned"))   # a new list: ask about its deals
            if self._digest_due and not "".join(said).rstrip().endswith("?"):  # ...once Kart's own question is answered
                self._digest_due = False
                async for out in self._offer_digest():
                    yield out
        elif isinstance(event, UserCustomSent):
            meta = event.metadata or {}
            if meta.get("type") == "member_forgotten":
                self._drop_member()
                self.member_id = None
                self.brain.remember(FORGOTTEN_NOTE, FORGOTTEN_LINE)   # a clean slate, and Claude knows why
                async for out in self._say([FORGOTTEN_LINE], interruptible=False):
                    yield out
                return
            if meta.get("type") == "member_idle":
                await self._ensure_profile()
                async for out in self._say([still_there_line(self._profile)], interruptible=False):
                    yield out
                return
            if meta.get("type") == "lull":
                await self._ensure_profile()
                line = self._next_question()
                self._question = line
                async for out in self._say([line], interruptible=False):
                    yield out
                return
            if meta.get("type") == "card_response" and str(meta.get("card_id", "")).startswith("digest"):
                answer = "yes" if meta.get("action") == "yes" else "no"
                ctx = self._ctx()
                async for out in self._digest_step(answer, ctx):
                    yield out
                return
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                await asyncio.sleep(self.coalesce_seconds)   # a paired deal suggestion arriving now replaces this line
            await self._refresh()
            if meta.get("type") == "suggestion" and self._avoided(meta.get("product_id")):
                await run_tool("dismiss_suggestion", {}, self._ctx())   # its card goes away; never offered again
                add, self._last_add = self._last_add, None
                got = proactive_line(add[0], self._catalog, self._plan, self._items, self._meal, self._nudges) \
                    if add and time.monotonic() - add[1] < ADD_THEN_DEAL_SECONDS else None
                if got:                                  # the deal cancelled the add's own line
                    async for out in self._say([got], interruptible=False):
                        yield out
                return
            line = proactive_line(meta, self._catalog, self._plan, self._items, self._meal, self._nudges)
            if meta.get("type") == "cart_changed" and meta.get("change") == "added":
                self._last_add = None                    # said (or nothing to say): a later deal stands alone
                if line and (money := self._budget_line()):
                    line = f"{line} {money}"
            if line and line.endswith(LIST_TOO):
                self._list_too, self._last_asked = meta.get("product_id"), "list_too"
            elif line and meta.get("type") == "suggestion" and self._last_add:
                add, at = self._last_add
                self._last_add = None
                got = proactive_line(add, self._catalog, self._plan, self._items, self._meal, self._nudges)
                if got and time.monotonic() - at < ADD_THEN_DEAL_SECONDS:   # the deal cancelled the add's own line
                    line = f"{got} {line}"
            if line:
                async for out in self._say([line], interruptible=False):
                    yield out

    # Deals: ask first, then one at a time --------------------------------------------------------------------

    async def _relevant_deals(self) -> list[dict[str, Any]]:
        """Live deals on something not on the list or in the cart that pair with the list, in route order (max 3)."""
        try:
            deals = await self.backend.get_live_deals()
        except Exception:
            return []
        catalog = {p["id"]: p for p in self._catalog}
        plan = [line.get("product_id") for line in self._plan]
        taken = set(plan) | {i.get("product_id") for i in self._items}
        found = []
        for deal in deals:
            product = catalog.get(deal.get("product_id"))
            pairs = [plan.index(p) for p in deal.get("pairs_with") or [] if p in plan]
            if self._avoided(deal.get("product_id")):
                continue
            asked = deal.get("id") in self._digest_asked or f"suggestion|{deal.get('id')}" in self._said
            if product is None or product.get("in_stock") is False or deal["product_id"] in taken or not pairs or asked:
                continue
            found.append((min(pairs), deal, product))
        return [{"deal": d, "product": p} for _, d, p in sorted(found, key=lambda x: x[0])][:3]

    async def _offer_digest(self) -> AsyncIterator[Any]:
        if self._quiet:                                  # "be quiet": the cards will still show at the shelf
            return
        await self._refresh()
        deals = await self._relevant_deals()
        if not deals:
            return
        for entry in deals:
            self._remember_offer(self._deal_line(entry))
        self._digest_asked |= {d["deal"]["id"] for d in deals}
        await asyncio.sleep(self.digest_delay_seconds)
        self._digest, self._last_asked = {"deals": deals, "i": -1}, "digest"
        n = len(deals)
        question = (f"By the way, one deal goes with your list. Want to hear it?" if n == 1
                    else f"By the way, {_count_word(n)} deals go with your list. Want to hear them?")
        yield AgentSendCustom(metadata={"type": "deal_digest", "count": n})
        async for out in self._say([question], interruptible=False):
            yield out

    def _deal_line(self, entry: dict[str, Any]) -> str:
        product, deal = entry["product"], entry["deal"]
        return f"{product.get('short_name') or product['name']} is {deal['label']} in {product.get('aisle')}. Want it?"

    async def _digest_step(self, answer: str, ctx: dict[str, Any]) -> AsyncIterator[Any]:
        digest = self._digest
        if digest is None:
            return
        if digest["i"] < 0 and answer != "yes":                     # "not now": each deal is said at its shelf
            self._digest = None
            yield AgentSendCustom(metadata={"type": "digest_done"})
            async for out in self._say(["No problem. I'll tell you at the shelf."], interruptible=False):
                yield out
            return
        prefix = ""
        if digest["i"] >= 0:                                         # the answer to the deal just read out
            entry = digest["deals"][digest["i"]]
            name = entry["product"].get("short_name") or entry["product"]["name"]
            if answer == "yes":
                await run_tool("add_to_plan", {"product_id": entry["product"]["id"], "reason": "deal"}, ctx)
                await self._refresh()
                prefix = f"Added {name} to your list. "
            else:
                prefix = "Okay. "
        digest["i"] += 1
        if digest["i"] < len(digest["deals"]):
            entry = digest["deals"][digest["i"]]
            self._said.add(f"suggestion|{entry['deal']['id']}")    # walked here: never read out again this trip
            line = self._deal_line(entry)
            yield AgentSendCustom(metadata={"type": "digest_deal", "deal_id": entry["deal"]["id"],
                                            "product_id": entry["product"]["id"], "text": line,
                                            "index": digest["i"] + 1, "count": len(digest["deals"])})
            async for out in self._say([prefix + line], interruptible=False):
                yield out
            return
        self._digest = None
        yield AgentSendCustom(metadata={"type": "digest_done"})
        async for out in self._say([prefix + "That's all the deals."], interruptible=False):
            yield out

    async def _caption_first(self, user_text: str, chunks: AsyncIterator[str]) -> AsyncIterator[str]:
        """The shopper's words reach the thread only once Kart answers, so chatter Kart stays quiet on never shows."""
        first = True
        async for chunk in chunks:
            if first:
                first = False
                await self._caption("user", user_text)
            yield chunk

    async def _say(self, chunks: Any, interruptible: bool = True) -> AsyncIterator[AgentSendText]:
        """Speaks chunks as they arrive and captions whatever was actually said, even if the shopper cuts in."""
        spoken: list[str] = []
        self._speaking = True
        try:
            if hasattr(chunks, "__aiter__"):
                async for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk, interruptible=interruptible)
            else:
                for chunk in chunks:
                    spoken.append(chunk)
                    yield AgentSendText(text=chunk, interruptible=interruptible)
            if self._pending:                            # a deal or cart line that waited for Kart to finish
                await self._flush_caption(spoken)
                spoken = [self._pending]
                self._pending = None
                yield AgentSendText(text=spoken[0], interruptible=False)
        finally:
            self._speaking = False
            await self._flush_caption(spoken)

    async def _flush_caption(self, spoken: list[str]) -> None:
        if spoken:
            text = "".join(spoken).strip()
            self._kart_asked = text.endswith("?")
            spoken.clear()
            await asyncio.shield(asyncio.ensure_future(self._caption("agent", text)))

    async def _caption(self, role: str, text: str) -> None:
        try:
            await self.backend.rpc("append_transcript", p_cart_id=self.cart_id, p_role=role, p_text=text)
        except Exception:
            pass                                          # captions must never break the conversation

    # Member memory -------------------------------------------------------------------------------

    def _drop_member(self) -> None:
        """The member is gone (forgotten, "not me", signed out): their prompt, tools and everything said so far."""
        had_member = self._profile is not None or self.member_id is not None
        self._profile, self._profile_tried, self._question, self._list_offer = None, False, None, None
        self.brain.set_member(None)
        if had_member:
            self.brain.messages = []                     # the history mentions them; Claude must not

    def _next_question(self) -> str:
        line = question(self._profile, self._questions)
        self._asked = True
        if self._profile and (self._profile.get("member") or {}).get("name"):
            self._questions += 1                         # the name question doesn't use up the rotation
        return line

    async def _ensure_profile(self) -> None:
        if self.member_id and not self._profile_tried:
            await self._load_profile()

    async def _load_profile(self) -> None:
        """What Kart remembers about the signed-in member; a slow or failed read leaves it out (never blocks)."""
        self._profile_tried = True
        try:
            profile = await asyncio.wait_for(
                self.backend.rpc("member_profile", p_member_id=self.member_id, p_cart_id=self.cart_id),
                self.profile_timeout_seconds)
        except Exception:
            profile = None
        if profile is None and self._profile and (self._profile.get("member") or {}).get("member_id") == self.member_id:
            return                                       # a slow reload keeps what Kart already knew this trip
        self._profile = profile
        self.brain.set_member(member_section(self._profile))

    async def _what_this_is(self) -> str:
        """What "this" or "that" can mean right now: the card on screen, and the last item into the cart."""
        if self._unknown_open:                           # still open? the item may have come out by itself
            try:
                self._unknown_open = bool(await self.backend.unresolved_events(self.cart_id, self.trip_id))
            except Exception:
                pass
        seen = []
        if self._unknown_open:
            seen.append('On screen: an "Is this...?" card for an item the cameras couldn\'t identify.')
        elif self._nudge and self._nudge.get("text"):
            seen.append(f'On screen: "{self._nudge["text"]}"')
        product = next((p for p in self._catalog if p["id"] == self._latest_added), None)
        if product:
            seen.append(f"The last item into the cart: {product.get('short_name') or product['name']}.")
        return " ".join(seen)

    async def _rejoin(self) -> None:
        """A new call on a trip in progress (a dropped call, a paused one, an app relaunch): pick up the meal, the
        conversation so far and the deals already asked about, so Kart carries on instead of starting over."""
        reasons = [line.get("meal") or line.get("reason") for line in self._plan
                   if (line.get("meal") or line.get("reason")) not in (None, "", "deal")]
        if reasons and not self._meal:
            self._meal = Counter(reasons).most_common(1)[0][0]
        try:
            lines = after_last_drop(await self.backend.get_transcript(self.cart_id, self.trip_id))   # member beta
        except Exception:
            lines = []
        self.brain.seed([(line.get("role", ""), line.get("text", "")) for line in lines])
        self._digest_asked |= {entry["deal"]["id"] for entry in await self._relevant_deals()}

    def _budget_line(self) -> str:
        """Once near the budget ("You're at $27.40 of $30.") and once over it, said with the "Got the X" line."""
        if self._budget is None:
            return ""
        budget = float(self._budget)
        cap = f"${budget:g}" if budget.is_integer() else f"${budget:.2f}"
        if self._total > budget and "budget|over" not in self._said:
            self._said |= {"budget|over", "budget|near"}
            return f"That's ${self._total:.2f}, over your {cap}."
        if self._total >= 0.9 * budget and "budget|near" not in self._said:
            self._said.add("budget|near")
            return f"You're at ${self._total:.2f} of {cap}."
        return ""

    def _live_note(self) -> str:
        """ "(Right now: list: Spaghetti ✓ (Aisle 6); Marinara (Aisle 6). Cart: Spaghetti ×1 $1.99. Total $1.99, saved
        $0.00. Next: Aisle 6 → Marinara.)", or "" before there's a list or anything in the cart."""
        plan, items = self._cart.get("plan") or [], self._cart.get("items") or []
        if not plan and not items:
            return ""
        names = {p["id"]: p.get("short_name") or p["name"] for p in self._catalog}

        def listed(line: dict[str, Any]) -> str:
            name = line.get("name") or names.get(line.get("product_id"), line.get("product_id"))
            qty = line.get("qty") or 1
            notes = [n for n in (line.get("aisle"), line.get("deal_label"),
                                 "sold out" if line.get("in_stock") is False else None) if n]
            return (f"{qty}× {name}" if qty > 1 else name) + (" ✓" if line.get("done") else "") + \
                (f" ({', '.join(notes)})" if notes else "")

        parts = [f"list: {'; '.join(listed(line) for line in plan)}"] if plan else []
        if items:
            parts.append("Cart: " + ", ".join(f"{i.get('short_name') or i.get('name') or names.get(i.get('product_id'))} "
                                              f"×{i.get('qty', 1)} ${float(i.get('price') or 0):.2f}" for i in items))
        parts.append(f"Total ${float(self._cart.get('total') or 0):.2f}, saved ${float(self._cart.get('savings') or 0):.2f}")
        if self._cart.get("budget") is not None:
            trip = float(self._cart.get("total") or 0) + float(self._cart.get("plan_estimate") or 0)
            parts.append(f"Budget ${float(self._cart['budget']):g}, the trip comes to about ${trip:.2f}")
        if self._cart.get("next_step"):
            parts.append(f"Next: {self._cart['next_step']}")
        return "(Right now: " + ". ".join(parts) + ".)"

    def _remember_offer(self, text: str) -> None:
        said = re.sub(r"\s*Want (it|them)\?$", "", text).strip()
        if said and said not in self._offered:
            self._offered.append(said)

    def _ctx(self) -> dict[str, Any]:
        """What the tools get: the backend, this cart and trip, the trip's undo history, and the signed-in member."""
        return {"backend": self.backend, "cart_id": self.cart_id, "trip_id": self.trip_id, "undo": self._undo,
                "diet": self._diet, "skipped": self._skipped, "member_id": self.member_id, "profile": self._profile}

    def _avoided(self, product_id: Any) -> bool:
        """Off-diet for this trip ("no dairy" -> cheese and dairy), or taken off the list: no deal on it is offered."""
        product = next((p for p in self._catalog if p["id"] == product_id), None)
        return product_id in self._skipped or product_id in (self._diet.get("products") or set()) or \
            (product is not None and (product.get("category") or "").lower() in (self._diet.get("kinds") or set()))

    async def _refresh(self) -> None:
        try:
            cart = await self.backend.get_cart(self.cart_id)
            self.trip_id = self.trip_id or cart.get("trip_id")
            self._plan = cart.get("plan", [])
            self._items = cart.get("items", [])
            self._nudges = bool((cart.get("features") or {}).get("quantity_nudges"))
            self._budget, self._total = cart.get("budget"), float(cart.get("total") or 0)
            self._cart = cart
            live = cart.get("nudge") if "nudge" in cart else self._nudge
            if self._nudge and not (live and (live.get("product_id"), live.get("kind")) ==
                                    (self._nudge.get("product_id"), self._nudge.get("kind"))):
                self._nudge = None                       # cleared or replaced on the cart: nothing left to answer
            self._catalog = self._catalog or await self.backend.get_catalog()
            self.brain.set_catalog(self._catalog)
        except Exception:
            pass
