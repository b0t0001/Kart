#!/usr/bin/env python3
"""Rebuild what the iPad showed during a logged trip, as a replay the app plays on the simulator for a screen recording
(the app's `-KartReplay` mode). The result is a reconstruction from the logs, not the original screen.

  agent/.venv/bin/python tools/ipad_replay.py build SPEC.json OUT_DIR
  python3 tools/ipad_replay.py record OUT_DIR VIDEO.mp4      # after building the app for the simulator

SPEC.json  the trip (cart, trip id, first and last frame in UTC), the cart's feature switches, and the moments the logs
           don't hold: plan edits, card taps and Pay, each with a note saying where its time comes from.
OUT_DIR    -> replay.json (every event at seconds from the first frame), catalog.json (data/store.json's shape, from
           the hosted catalog), member_profile.json (the hosted member_profile answer), sources.md (what came from where)

Reads the hosted backend with the anon key only (transcript, cart_events, receipts, the catalog and member_profile,
which is read-only): it never writes, so cart and catalog are untouched.

record: launches the app in replay mode on the iPad simulator (DEVICE, default iPad Pro 11-inch (M5), light mode),
records it with `simctl io recordVideo --codec h264`, and trims the video so its first frame is t = 0 (the spec's
start_utc) and it runs to end_utc; VIDEO.txt beside it says so. Build first: ios/scripts/shoot.sh builds, or
xcodebuild -scheme Kart -derivedDataPath ios/build for the simulator.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def build(spec_path: str, out_dir: str) -> None:
    import httpx

    spec = json.loads(Path(spec_path).read_text())
    url, key = os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def get(table: str, **params: str) -> list[dict]:
        r = httpx.get(f"{url}/rest/v1/{table}", headers=headers, params={"select": "*", **params}, timeout=15)
        r.raise_for_status()
        return r.json()

    zero, end = utc(spec["start_utc"]), utc(spec["end_utc"])
    last = utc(spec.get("events_until_utc", spec["end_utc"]))
    since = (zero.timestamp() - 60)
    t = lambda moment: round(utc(moment).timestamp() - zero.timestamp(), 3)

    events: list[dict] = []
    for row in get("transcript", cart_id=f"eq.{spec['cart_id']}", trip_id=f"eq.{spec['trip_id']}", order="id.asc"):
        if since <= utc(row["created_at"]).timestamp() <= last.timestamp():
            events.append({"t": t(row["created_at"]), "action": "caption", "role": row["role"], "text": row["text"]})
    for row in get("cart_events", trip_id=f"eq.{spec['trip_id']}", order="id.asc"):
        if row["applied"] and utc(row["created_at"]).timestamp() <= last.timestamp():
            events.append({"t": t(row["created_at"]), "action": "vision", "type": row["type"],
                           "product_id": row["product_id"], "confidence": row["confidence"], "label": row["label"]})
    for note in spec["moments"]:
        event = {k: v for k, v in note.items() if k not in ("at_utc", "source")}
        events.append({"t": t(note["at_utc"]), **event})
    events.sort(key=lambda e: e["t"])

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "replay.json").write_text(json.dumps({
        "label": spec["label"], "catalog": "catalog.json", "member_profile": "member_profile.json" if spec.get("member_id") else None,
        "features": spec["features"], "events": events}, indent=1, ensure_ascii=False))
    (out / "window.json").write_text(json.dumps({"start_utc": spec["start_utc"], "start_local": spec.get("start_local"),
                                                 "status_time": spec.get("status_time"),
                                                 "seconds": round(end.timestamp() - zero.timestamp(), 3)}))

    store = get("store_info")[0]
    sections = [{k: s[k] for k in ("id", "name", "x", "y", "w", "h")} for s in get("sections", order="x.asc")]
    products = [{**{k: p[k] for k in ("id", "name", "short_name", "price", "section", "category", "tags")},
                 "stock": max(p["stock"], spec.get("min_stock", 0))}         # in stock as during the trip
                for p in get("products", active="eq.true", order="sort.asc")]
    deals = [{k: d[k] for k in ("id", "product_id", "type", "value", "label", "pairs_with", "ends_at")}
             for d in get("deals", active="eq.true", order="sort.asc")]
    (out / "catalog.json").write_text(json.dumps({
        "version": 6, "store": {"name": store["name"], "width": store["width"], "height": store["height"]},
        "entrance": {"x": store["entrance_x"], "y": store["entrance_y"]},
        "sections": sections, "products": products, "deals": deals}, indent=1, ensure_ascii=False))

    if spec.get("member_id"):
        r = httpx.post(f"{url}/rest/v1/rpc/member_profile", headers=headers, timeout=15,
                       json={"p_member_id": spec["member_id"], "p_cart_id": spec["cart_id"]})
        r.raise_for_status()
        (out / "member_profile.json").write_text(json.dumps(r.json(), indent=1, ensure_ascii=False))

    receipt = next((r for r in get("receipts", cart_id=f"eq.{spec['cart_id']}", trip_id=f"eq.{spec['trip_id']}")), None)
    lines = [f"# {spec['label']}", "", f"First frame = {spec['start_utc']} ({spec.get('start_local', '')}), "
             f"last = {spec['end_utc']}: {round(end.timestamp() - zero.timestamp(), 1)} s.", "",
             f"- {sum(e['action'] == 'caption' for e in events)} captions, verbatim from `transcript` at their logged times",
             f"- {sum(e['action'] == 'vision' for e in events)} camera adds/removes from `cart_events` at their logged times",
             "- Catalog and deals: the hosted catalog as it is now (layout "
             f"{store.get('layout')}); member profile: hosted `member_profile` as it is now",
             f"- Receipt: {receipt['total'] if receipt else '?'} total, {receipt['savings'] if receipt else '?'} saved, "
             f"{receipt['duration_s'] if receipt else '?'} s (paid {receipt['created_at'] if receipt else '?'})", "",
             "Moments the logs don't hold:", ""]
    lines += [f"- t={t(m['at_utc']):+.2f} s {m['action']}: {m['source']}" for m in spec["moments"]]
    (out / "sources.md").write_text("\n".join(lines) + "\n")
    print(f"{out}/replay.json: {len(events)} events, {events[0]['t']:+.1f} to {events[-1]['t']:+.1f} s")


APP = Path(__file__).resolve().parents[1] / "ios/build/Build/Products/Debug-iphonesimulator/Kart.app"


def sh(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True).stdout


def record(replay_dir: str, video: str) -> None:
    replay = Path(replay_dir).resolve()
    window = json.loads((replay / "window.json").read_text())
    seconds, preroll = window["seconds"], -min(0.0, min(e["t"] for e in json.loads((replay / "replay.json").read_text())["events"]))
    device = os.environ.get("DEVICE", "iPad Pro 11-inch (M5)")
    match = re.search(re.escape(device) + r" \(([0-9A-F-]{36})\)", sh("xcrun", "simctl", "list", "devices", "available"))
    if not match:
        sys.exit(f"no simulator named {device}")
    udid = match.group(1)
    subprocess.run(["xcrun", "simctl", "boot", udid], capture_output=True)
    sh("xcrun", "simctl", "bootstatus", udid, "-b")
    sh("xcrun", "simctl", "ui", udid, "appearance", "light")
    if window.get("status_time"):                         # the terminal shows the status bar: the trip's clock, not now
        sh("xcrun", "simctl", "status_bar", udid, "override", "--time", window["status_time"],
           "--batteryState", "charged", "--batteryLevel", "100", "--wifiBars", "3")
    sh("xcrun", "simctl", "install", udid, str(APP))
    subprocess.run(["xcrun", "simctl", "terminate", udid, "com.kart.app"], capture_output=True)

    zero = time.time() + 8 + preroll                     # the app's t = 0, with time to launch and settle first
    sh("xcrun", "simctl", "launch", udid, "com.kart.app", "-KartReplay", str(replay / "replay.json"),
       "-KartReplayAt", f"{zero:.3f}", "-KartTapToPay", "YES")
    raw = Path(video).with_suffix(".raw.mp4")
    time.sleep(max(0.0, zero - 3 - time.time()))
    recorder = subprocess.Popen(["xcrun", "simctl", "io", udid, "recordVideo", "--codec", "h264", "--force", str(raw)],
                                stderr=subprocess.PIPE, text=True)
    started: list[float] = []

    def watch() -> None:
        for line in recorder.stderr:                    # "Recording started" marks the first frame
            if "started" in line.lower() and not started:
                started.append(time.time())

    threading.Thread(target=watch, daemon=True).start()
    time.sleep(max(0.0, zero + seconds + 0.6 - time.time()))
    recorder.send_signal(signal.SIGINT)
    recorder.wait(timeout=30)
    if not started:
        sys.exit("simctl never said the recording started")
    if window.get("status_time"):
        subprocess.run(["xcrun", "simctl", "status_bar", udid, "clear"], capture_output=True)
    offset = zero - started[0]
    probe = sh("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(raw))
    width, height = (int(v) for v in probe.strip().split(","))
    # An upright (portrait) simulator letterboxes the landscape app into the middle of the frame at 2/3 size: the top
    # rows come out black. Turned to landscape (KartUITests/OrientationTests), the app fills the frame, sideways.
    top = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(raw), "-frames:v", "1", "-vf", "crop=iw:8:0:16,scale=32:1",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], check=True, capture_output=True).stdout
    if height > width and max(top) < 24:
        sys.exit(f"{device} is upright, so the recording is letterboxed: turn it to landscape first (xcodebuild test "
                 "-only-testing:KartUITests/OrientationTests/testRotateToLandscape on this simulator), then record again")
    rotate = "transpose=2," if height > width else ""     # a landscape-only app on a portrait framebuffer
    # simctl writes a frame only when the screen changes: resample to a steady 30 fps from the raw start, cut out
    # t = 0 .. end, and hold the last frame if the screen sat still to the end.
    chain = (f"fps=30,trim=start={offset:.3f}:duration={seconds:.3f},setpts=PTS-STARTPTS,"
             f"tpad=stop_mode=clone:stop_duration={seconds:.0f},{rotate}format=yuv420p")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf", chain, "-t", f"{seconds:.3f}", "-r", "30",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-movflags", "+faststart", "-an", video], check=True)
    raw.unlink()
    Path(video).with_suffix(".txt").write_text(
        f"{Path(video).name}: the iPad screen for this take, RECONSTRUCTED from the logs on the {device} simulator,\n"
        f"not the original screen (see {replay.name}/sources.md for what came from where).\n\n"
        f"First frame = {window['start_utc']} = {window.get('start_local') or ''} (wall-clock offset 0.000 s).\n"
        f"Duration {seconds:.1f} s, so frame time + {window.get('start_local') or window['start_utc']} = real time.\n"
        f"Recording started {offset:.3f} s before t = 0 and was trimmed to t = 0 (±0.1 s).\n")
    print(f"{video}: {seconds:.1f} s from {window['start_utc']}, trimmed {offset:.2f} s of lead-in")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "build":
        build(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "record":
        record(sys.argv[2], sys.argv[3])
    else:
        sys.exit(__doc__)
