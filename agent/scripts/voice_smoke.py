"""One voice call to the deployed Line agent, speaking like the iPad (LineCodec), on a test cart: the greeting, one
spoken line (macOS `say` at 16 kHz), and the time from the end of speech to Kart's first audio. Never prints the token.

  cd agent && set -a && . ../.env && set +a
  ../backend/.venv/bin/python ../backend/cart.py reset --cart ipad-voice      # voice-token needs the cart to exist
  .venv/bin/python scripts/voice_smoke.py ipad-voice "I'm making a pasta dinner for my family."
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
import wave

import httpx
import websockets

URL, KEY = os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"]
CART, SAY = sys.argv[1], sys.argv[2]
if CART == "7":
    sys.exit("Use a test cart: cart 7 is the demo cart.")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
CHUNK = 640  # 20 ms of 16 kHz PCM16


def speech_pcm(text: str) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav") as f:
        subprocess.run(["say", "-o", f.name, "--file-format=WAVE", "--data-format=LEI16@16000", text], check=True)
        with wave.open(f.name) as w:
            assert w.getframerate() == 16000 and w.getsampwidth() == 2 and w.getnchannels() == 1
            return w.readframes(w.getnframes())


async def main() -> None:
    token = httpx.post(f"{URL}/functions/v1/voice-token", headers=H, json={"cart_id": CART}, timeout=15).json()
    cart = httpx.get(f"{URL}/rest/v1/carts", headers=H, params={"cart_id": f"eq.{CART}", "select": "trip_id"}).json()[0]
    ws_url = f"{token['ws_url']}?cartesia_version={token['cartesia_version']}&access_token={token['token']}"
    sid = str(uuid.uuid4())
    t0 = time.monotonic()
    media: list[tuple[float, int]] = []          # (time, bytes) of each media_output
    others: list[tuple[float, str]] = []
    first_audio: list[bytes] = []
    deltas: dict = {}

    async with websockets.connect(ws_url, max_size=None) as ws:
        async def reader() -> None:
            async for raw in ws:
                now = time.monotonic() - t0
                msg = json.loads(raw)
                ev = msg.get("event")
                if ev == "media_output":
                    pcm = base64.b64decode(msg["media"]["payload"])
                    media.append((now, len(pcm)))
                    first_audio.append(pcm)
                elif ev == "turn_output_text_delta":
                    tid = msg[ev].get("id")
                    if tid not in deltas:
                        deltas[tid] = now
                        others.append((now, f"first text delta of turn {tid}"))
                else:
                    shown = {k: v for k, v in msg.items() if k not in ("media", "stream_id")}
                    others.append((now, json.dumps(shown)[:220]))

        task = asyncio.create_task(reader())
        await ws.send(json.dumps({"event": "start", "stream_id": sid, "config": {"input_format": "pcm_16000"}}))
        await asyncio.sleep(0.3)
        await ws.send(json.dumps({"event": "custom", "stream_id": sid,
                                  "metadata": {"type": "trip_context", "cart_id": CART, "trip_id": cart["trip_id"]}}))

        silence = bytes(CHUNK)
        async def stream(pcm: bytes) -> None:
            for i in range(0, len(pcm), CHUNK):
                await ws.send(json.dumps({"event": "media_input", "stream_id": sid,
                                          "media": {"payload": base64.b64encode(pcm[i:i + CHUNK].ljust(CHUNK, b"\0")).decode()}}))
                await asyncio.sleep(0.02)

        # Let the greeting play out (silence keeps the stream alive, as the iPad's mic would).
        greet_deadline = time.monotonic() + 12
        while time.monotonic() < greet_deadline:
            await stream(silence * 10)
            if media and time.monotonic() - t0 - media[-1][0] > 1.5:
                break
        greeting_bytes = sum(b for _, b in media)
        greeting_span = (media[0][0], media[-1][0]) if media else None
        n_greeting = len(media)

        speech = speech_pcm(SAY)
        await stream(speech)
        spoke_end = time.monotonic() - t0
        reply_deadline = time.monotonic() + 20
        while time.monotonic() < reply_deadline:
            await stream(silence * 10)
            if len(media) > n_greeting and time.monotonic() - t0 - media[-1][0] > 2.0:
                break
        task.cancel()

    reply = media[n_greeting:]
    print("events:", *[f"  {t:6.2f}s {s}" for t, s in others], sep="\n")
    print(f"greeting: {n_greeting} chunks, {greeting_bytes} bytes, first at {greeting_span[0]:.2f}s" if greeting_span else "greeting: none")
    print(f"speech: {len(speech)} bytes ({len(speech) / 32000:.2f}s), ended at {spoke_end:.2f}s")
    if reply:
        print(f"reply: {len(reply)} chunks, {sum(b for _, b in reply)} bytes, first audio {reply[0][0] - spoke_end:.2f}s after speech ended")
    else:
        print("reply: none")
    if first_audio:
        seconds = sum(len(c) for c in first_audio[:n_greeting]) / 32000
        print(f"greeting audio: {seconds:.2f}s at 16 kHz PCM16 (the iPad plays it at EngineAudio.outputSampleRate)")


asyncio.run(main())
