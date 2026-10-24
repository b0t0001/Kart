import json

import main
from helpers import SYNTH, world

from kartcv.sources import save_tick
from kartcv.synth import Item, Scene, Script


def test_replay_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KART_ENV_FILE", str(tmp_path / "none"))
    for k in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "CART_ID"):
        monkeypatch.delenv(k, raising=False)
    w = world(tmp_path / "w")
    store = tmp_path / "store.json"
    store.write_text(json.dumps({"products": [{"id": i.item_id, "name": i.item_id, "price": 1.0} for i in SYNTH]}))
    rec = tmp_path / "rec"
    for t in Script(Scene()).still(1.0).drop(Item("red-box", 300, 200, seed=1)).ticks:
        save_tick(rec, t)
    cfg = tmp_path / "cfg.json"
    cfg.write_text('{"features": "hist"}')
    rc = main.main(["replay", str(rec), "--no-cloud", "--state", str(tmp_path / "state"),
                    "--gallery", str(w.gallery.root), "--catalog", str(store), "--config", str(cfg)])
    lines = (tmp_path / "state/events.jsonl").read_text().splitlines()
    assert rc == 0 and [json.loads(line)["type"] for line in lines] == ["added"]
    assert "ADDED red-box" in capsys.readouterr().out


def test_replay_never_touches_the_live_cart_or_the_backend(tmp_path, monkeypatch, capsys):
    # On the Pi the .env has Supabase and the live cart's state is in pi/state: a replay must use neither.
    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=https://example.supabase.co\nSUPABASE_ANON_KEY=k\n")
    monkeypatch.setenv("KART_ENV_FILE", str(env))
    for k in ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "CART_ID"):
        monkeypatch.delenv(k, raising=False)
    built = []
    monkeypatch.setattr(main, "HttpSink", lambda *a, **kw: built.append(a) or (_ for _ in ()).throw(AssertionError))
    w = world(tmp_path / "w")
    store = tmp_path / "store.json"
    store.write_text(json.dumps({"products": [{"id": i.item_id, "name": i.item_id, "price": 1.0} for i in SYNTH]}))
    rec = tmp_path / "rec"
    for t in Script(Scene()).still(1.0).drop(Item("red-box", 300, 200, seed=1)).ticks:
        save_tick(rec, t)
    live = tmp_path / "live-state"
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({"features": "hist", "state_dir": str(live)}))
    rc = main.main(["replay", str(rec), "--no-cloud", "--gallery", str(w.gallery.root), "--catalog", str(store),
                    "--config", str(cfg)])
    assert rc == 0 and built == [] and not live.exists()
    assert "ADDED red-box" in capsys.readouterr().out
