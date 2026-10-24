from kartcv.config import Config, load_config, load_env


def test_defaults_match_spec():
    c = Config()
    assert (c.motion_size, c.motion_thresh, c.motion_frac, c.settle_s) == ((320, 180), 25, 0.005, 1.0)
    assert (c.diff_size, c.change_thresh, c.min_blob_frac, c.disturbed_frac) == ((640, 360), 30.0, 0.004, 0.60)
    assert (c.empty_thresh, c.crop_pad, c.local_min_score, c.local_min_margin) == (18.0, 0.10, 0.70, 0.08)
    assert (c.cloud_model, c.cloud_min_conf, c.cloud_timeout_s, c.server_port) == ("claude-haiku-5-5", 0.6, 6.0, 8080)


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
