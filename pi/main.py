#!/usr/bin/env python3
"""KART cart vision.

  python pi/main.py live [--debug-view]      # watch the cameras (what the Pi's service runs)
  python pi/main.py replay tools/out/rec-…   # run the pipeline on a recording
  python pi/main.py reset                    # empty-cart reset (cart must be empty)
"""
from __future__ import annotations

import argparse
import logging
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kartcv import http  # noqa: E402
from kartcv.catalog import fetch_catalog, load_catalog  # noqa: E402
from kartcv.config import REPO_ROOT, load_config, load_env  # noqa: E402
from kartcv.identify.cloud import CloudIdentifier  # noqa: E402
from kartcv.identify.features import load_features  # noqa: E402
from kartcv.identify.gallery import Gallery  # noqa: E402
from kartcv.identify.hybrid import HybridIdentifier  # noqa: E402
from kartcv.pipeline import Pipeline  # noqa: E402
from kartcv.roi import draw_outline  # noqa: E402
from kartcv.server import ControlServer  # noqa: E402
from kartcv.sinks import ConsoleSink, HttpSink, JsonlSink  # noqa: E402
from kartcv.sources import LiveCamera, iter_ticks, load_recording  # noqa: E402
from kartcv.trip import TripWatcher  # noqa: E402

log = logging.getLogger("kart")
TICK_S = 0.1


def _catalog(cfg, env, args):
    if getattr(args, "catalog", None):
        cat = load_catalog(Path(args.catalog))
        log.info("catalog: %d products from %s", len(cat.ids()), args.catalog)
        return cat
    if env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"):
        cat = fetch_catalog(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"])
        if cat is not None:
            log.info("catalog: %d products from Supabase", len(cat.ids()))
            return cat
    cat = load_catalog(cfg.path("catalog_path"))
    log.info("catalog: %d products from %s", len(cat.ids()), cfg.path("catalog_path"))
    return cat


def build(cfg, env: dict, args, cams: list[int], send_events: bool = True, background: bool = False):
    if env.get("CART_ID"):
        cfg.cart_id = env["CART_ID"]
    state_dir = Path(args.state) if getattr(args, "state", None) else cfg.path("state_dir")
    catalog = _catalog(cfg, env, args)
    features = load_features(cfg.path("model_path"), cfg.features)
    gallery = Gallery(Path(args.gallery) if getattr(args, "gallery", None) else cfg.path("gallery_dir"), features)
    gallery.load()
    log.info("features: %s; gallery: %d products", features.name, len(gallery.products()))

    cloud = None
    if env.get("ANTHROPIC_API_KEY") and not getattr(args, "no_cloud", False):
        cloud = CloudIdentifier(catalog, cfg.cloud_model, cfg.cloud_timeout_s)
    else:
        log.warning("local-only mode: no Claude fallback (ANTHROPIC_API_KEY unset or --no-cloud)")
    identifier = HybridIdentifier(gallery, cloud, catalog, cfg)

    sinks = [JsonlSink(state_dir / "events.jsonl"), ConsoleSink()]
    if send_events and env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY"):
        sinks.append(HttpSink(env["SUPABASE_URL"], env["SUPABASE_ANON_KEY"], state_dir / "outbox.jsonl"))
        log.info("events → Supabase apply_cart_event (cart %s)", cfg.cart_id)
    elif send_events:
        log.warning("no Supabase settings: events go to %s only", state_dir / "events.jsonl")
    pipeline = Pipeline(cfg, cams, identifier, features, sinks, state_dir, background=background)
    pipeline.catalog = catalog
    return pipeline, sinks


def _close(sinks) -> None:
    for s in sinks:
        s.close()


def cmd_live(cfg, env, args) -> int:
    if args.debug_view:
        cfg.debug_view = True
    cams = [LiveCamera(k, src, cfg.width, cfg.height, cfg.fps, warmup_s=cfg.camera_warmup_s)
            for k, src in enumerate(cfg.cameras)]
    # judge in the background: a Claude call must never stop the cameras from being watched
    pipeline, sinks = build(cfg, env, args, [c.cam for c in cams], background=True)
    extras = start_extras(cfg, env, pipeline)
    log.info("watching %d camera(s); Ctrl-C to stop", len(cams))
    try:
        while True:
            t0 = time.monotonic()
            pipeline.step({c.cam: c.read() for c in cams})
            time.sleep(max(0.0, TICK_S - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        log.info("stopping")
    finally:
        for x in extras:
            x.stop()
        pipeline.close()
        for c in cams:
            c.close()
        _close(sinks)
    return 0


def start_extras(cfg, env, pipeline) -> list:
    """Live-mode helpers: the control server (status/reset/debug page) and the new-trip watcher."""
    extras = []
    try:
        server = ControlServer(cfg.server_port, pipeline.status, pipeline.request_reset,
                               frames_fn=pipeline.latest_frames, debug_view=cfg.debug_view,
                               overlay_fn=lambda cam, img: draw_outline(img, cfg.roi.get(str(cam))),
                               crops_dir=pipeline.crops_dir)
        server.start()
        extras.append(server)
    except OSError as e:  # e.g. port taken: the cart keeps working without it
        log.warning("control server not started on :%d (%s)", cfg.server_port, e)

    url, key = env.get("SUPABASE_URL"), env.get("SUPABASE_ANON_KEY")
    if url and key:
        def on_new_trip():
            pipeline.request_reset()
            fresh = fetch_catalog(url, key)  # products the owner added live are known from the next trip
            if fresh is not None:
                pipeline.catalog.replace_with(fresh)
                log.info("catalog refreshed: %d products", len(fresh.ids()))

        extras.append(TripWatcher(url, key, cfg.cart_id, pipeline.state_dir / "trip.json", on_new_trip))
    return extras


def cmd_replay(cfg, env, args) -> int:
    sources = load_recording(Path(args.dir))
    if not sources:
        print(f"no cam*/ folders in {args.dir}")
        return 1
    # A replay is a rehearsal: its own scratch state (never the live cart's memory or empty pictures)
    # and no events to the backend (it must not bill the real cart), even on the Pi with its .env.
    if not args.state:
        args.state = tempfile.mkdtemp(prefix="kart-replay-")
    pipeline, sinks = build(cfg, env, args, [s.cam for s in sources], send_events=False)
    n = 0
    for tick in iter_ticks(sources):
        n += len(pipeline.step(tick))
    _close(sinks)
    print(f"replay done: {n} event(s); log and crops in {args.state}")
    return 0


def cmd_reset(cfg, env, args) -> int:
    try:
        status = http.post_json(f"http://127.0.0.1:{cfg.server_port}/reset", {}, {}, timeout=3.0)
        print("reset requested from the running cart" if status == 200 else f"reset failed: HTTP {status}")
        return 0 if status == 200 else 1
    except OSError:
        state_dir = Path(args.state) if args.state else cfg.path("state_dir")
        (state_dir / "cart.json").unlink(missing_ok=True)
        for p in state_dir.glob("empty_cam*.jpg"):
            p.unlink()
        print("cart vision isn't running; next start will reset (make sure the cart is empty)")
        return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=REPO_ROOT / "pi/config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    live = sub.add_parser("live")
    live.add_argument("--debug-view", action="store_true")
    rep = sub.add_parser("replay")
    rep.add_argument("dir")
    rep.add_argument("--no-cloud", action="store_true")
    rep.add_argument("--gallery")
    rep.add_argument("--catalog")
    for p in (live, rep, sub.add_parser("reset")):
        p.add_argument("--config", type=Path, default=argparse.SUPPRESS)
        p.add_argument("--state")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    env = load_env()
    cfg = load_config(args.config)
    return {"live": cmd_live, "replay": cmd_replay, "reset": cmd_reset}[args.cmd](cfg, env, args)


if __name__ == "__main__":
    sys.exit(main())
