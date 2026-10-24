"""End-to-end against a real Supabase (local: http://127.0.0.1:54321). Opt-in:

  KART_E2E=1 pi/.venv/bin/python -m pytest pi/tests/test_e2e_supabase.py -q

Uses SUPABASE_URL / SUPABASE_ANON_KEY from the shared .env and a throwaway cart id, so the demo
cart "7" is never touched. Covers: live catalog fetch, replayed add/add/remove reaching the carts
row, an outbox retry of an already-applied event not double-adding, and reset_cart → trip_id change
clearing the cart's memory.
"""
import json
import os
import uuid
from dataclasses import replace

import pytest

from kartcv import http
from kartcv.catalog import fetch_catalog
from kartcv.config import Config, load_env
from kartcv.identify.features import HistogramFeatures
from kartcv.identify.gallery import Gallery
from kartcv.identify.hybrid import HybridIdentifier
from kartcv.pipeline import Pipeline
from kartcv.sinks import HttpSink, MemorySink
from kartcv.synth import Item, Scene, Script, crop_item
from kartcv.trip import TripWatcher

pytestmark = pytest.mark.skipif(os.environ.get("KART_E2E") != "1", reason="opt-in: KART_E2E=1 with Supabase in .env")

PARM, PASTA = "kirkland-parmesan", "barilla-spaghetti"


@pytest.fixture(scope="module")
def sb():
    env = load_env()
    if not (env.get("SUPABASE_URL") and env.get("SUPABASE_ANON_KEY")):
        pytest.skip("SUPABASE_URL / SUPABASE_ANON_KEY not set")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


def cart_row(sb, cart_id):
    url, key = sb
    status, body = http.get(f"{url}/rest/v1/carts?cart_id=eq.{cart_id}&select=items,total,trip_id",
                            http.supabase_headers(key))
    assert status == 200, body
    rows = json.loads(body)
    return rows[0] if rows else None


def qty(row, pid):
    return sum(int(i.get("qty", 0)) for i in (row or {}).get("items") or [] if i.get("product_id") == pid)


def test_replay_to_supabase_retry_and_trip_reset(tmp_path, sb):
    url, key = sb
    cart_id = f"cv-e2e-{uuid.uuid4().hex[:8]}"

    catalog = fetch_catalog(url, key)
    assert catalog is not None and {PARM, PASTA} <= set(catalog.ids())

    cfg = Config(features="hist", cart_id=cart_id)
    features = HistogramFeatures()
    gallery = Gallery(tmp_path / "gallery", features)
    gallery.load()
    parm, pasta = Item(PARM, 300, 200, seed=1), Item(PASTA, 560, 330, seed=2)
    for it in (parm, pasta):  # synthetic sprites enrolled under real catalog ids
        for x, y in [(300, 200), (520, 300)]:
            for cam in (0, 1):
                gallery.add(it.item_id, crop_item(cam, replace(it, x=x, y=y), pad=0.0))

    outbox = tmp_path / "state/outbox.jsonl"
    http_sink = HttpSink(url, key, outbox, start_thread=False)
    mem = MemorySink()
    p = Pipeline(cfg, [0, 1], HybridIdentifier(gallery, None, catalog, cfg), features, [http_sink, mem],
                 tmp_path / "state")

    # 1. a replayed add, add, remove reaches the carts row
    sc = Script(Scene()).still(1.0).drop(parm).drop(pasta).take(PARM)
    for tick in sc.ticks:
        p.step(tick)
    assert [(e.type, e.product_id, e.method) for e in mem.events] == \
        [("added", PARM, "local"), ("added", PASTA, "local"), ("removed", PARM, "memory")]
    assert http_sink.flush_once(1e9) == 3 and http_sink.pending() == 0
    row = cart_row(sb, cart_id)
    assert qty(row, PASTA) == 1 and qty(row, PARM) == 0 and float(row["total"]) > 0

    # 2. an outbox retry of an event the backend already applied must not double-add
    retry = HttpSink(url, key, tmp_path / "retry_outbox.jsonl", start_thread=False)
    retry.send(mem.events[1])  # same event_id as the PASTA add
    assert retry.flush_once(1e9) == 1
    assert qty(cart_row(sb, cart_id), PASTA) == 1

    # 3. reset_cart (what the iPad calls for a new trip) → trip_id changes → the Pi clears its memory
    watcher = TripWatcher(url, key, cart_id, tmp_path / "state/trip.json", p.request_reset, start_thread=False)
    first = watcher.poll_once()
    assert first and len(p.cart.instances) == 1
    assert http.post_json(f"{url}/rest/v1/rpc/reset_cart", http.supabase_headers(key), {"p_cart_id": cart_id}) == 200
    assert watcher.poll_once() not in (None, first)
    p.step(Script(Scene(items=[pasta])).still(0.1).ticks[0])
    assert len(p.cart.instances) == 0 and qty(cart_row(sb, cart_id), PASTA) == 0


def test_unknown_added_then_removed_is_resolved_in_the_backend(tmp_path, sb):  # review C1(d)
    url, key = sb
    cart_id = f"cv-e2e-{uuid.uuid4().hex[:8]}"
    catalog = fetch_catalog(url, key)
    cfg = Config(features="hist", cart_id=cart_id)
    gallery = Gallery(tmp_path / "gallery", HistogramFeatures())
    gallery.load()
    sink = HttpSink(url, key, tmp_path / "state/outbox.jsonl", start_thread=False)
    mem = MemorySink()
    p = Pipeline(cfg, [0, 1], HybridIdentifier(gallery, None, catalog, cfg), HistogramFeatures(), [sink, mem],
                 tmp_path / "state")
    for tick in Script(Scene(arm=False)).still(1.0).hand_rest(1.5).ticks:  # a hand that never reaches the edge
        p.step(tick)
    assert [(e.type, e.product_id) for e in mem.events] == [("added", None), ("removed", None)]
    assert sink.flush_once(1e9) == 2
    status, body = http.get(f"{url}/rest/v1/cart_events?cart_id=eq.{cart_id}&select=event_id,type,resolved_at&order=id",
                            http.supabase_headers(key))
    rows = json.loads(body)
    added = next(r for r in rows if r["type"] == "added")
    assert status == 200 and added["event_id"] == mem.events[0].event_id and added["resolved_at"] is not None
