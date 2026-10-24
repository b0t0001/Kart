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
