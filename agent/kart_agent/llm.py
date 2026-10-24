"""Claude through the official Anthropic SDK, streamed, with server-side refusal fallbacks."""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"


class AnthropicLLM:
    """Model and effort are config (KART_MODEL, KART_EFFORT) so voice latency can be tuned without code changes."""

    def __init__(self, client: anthropic.AsyncAnthropic | None = None, model: str | None = None, effort: str | None = None):
        self.client = client or anthropic.AsyncAnthropic()
        self.model = model or os.getenv("KART_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.getenv("KART_EFFORT", "low")

    async def stream(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> AsyncIterator[Any]:
        options: dict[str, Any] = {}
        if self.model.startswith(("claude-opus-5", "claude-fable", "claude-sonnet-5-5")):
            options = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=2048,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
            output_config={"effort": self.effort},
            **options,
        ) as stream:
            async for text in stream.text_stream:
                yield ("text", text)
            message = await stream.get_final_message()
        if message.stop_reason == "refusal":
            yield ("text", "Sorry, I can't help with that one.")
            yield ("final", [], "end_turn")
            return
        if message.stop_reason == "max_tokens" and any(b.type == "tool_use" for b in message.content):
            yield ("final", [b for b in message.content if b.type != "tool_use"], "end_turn")   # never run a truncated tool call
            return
        yield ("final", list(message.content), message.stop_reason)
