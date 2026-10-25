from kartcv.config import Config, load_config, load_env


def test_defaults_match_spec():
    c = Config()
    assert (c.motion_size, c.motion_thresh, c.motion_frac, c.settle_s) == ((320, 180), 25, 0.005, 1.0)
    assert (c.diff_size, c.change_thresh, c.min_blob_frac, c.disturbed_frac) == ((640, 360), 30.0, 0.004, 0.60)
    assert (c.empty_share, c.crop_pad, c.local_min_score, c.local_min_margin) == (0.20, 0.10, 0.70, 0.08)
    assert (c.cloud_model, c.cloud_min_conf, c.cloud_timeout_s, c.server_port) == ("claude-haiku-5-5", 0.6, 6.0, 8080)
    assert not c.edge_privacy and not c.personal_items and not c.claude_count  # stable path: all betas off
    assert c.features == "hist"  # review C3: the validated path; switch to "auto" after tools/gallery_check.py


def test_json_file_then_overrides(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"settle_s": 1.5, "cameras": ["/dev/v4l/by-path/a"], "diff_size": [320, 180], "bogus": 1}')
    c = load_config(p)
    assert c.settle_s == 1.5 and c.cameras == ["/dev/v4l/by-path/a"] and c.diff_size == (320, 180)
    assert load_config(p, {"settle_s": 2.0}).settle_s == 2.0


def test_load_env(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text("ANTHROPIC_API_KEY=sk-test\nCART_ID=9\n")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CART_ID", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.setenv("KART_ENV_FILE", str(f))
    assert load_env() == {"ANTHROPIC_API_KEY": "sk-test", "CART_ID": "9"}
    monkeypatch.setenv("KART_ENV_FILE", str(tmp_path / "missing"))
    load_env()  # no exception


def test_example_config_matches_the_locked_layout():  # 2 cams, 15 fps (30 overloads the shared USB 2 bus)
    import json
    from kartcv.config import REPO_ROOT
    ex = json.loads((REPO_ROOT / "pi/config.example.json").read_text())
    assert Config().fps == 15 and ex["fps"] == 15
    assert [c.split("usb-0:")[1].split(":")[0] for c in ex["cameras"]] == ["1.1", "1.3"]  # cam1 moved off loose 1.2
