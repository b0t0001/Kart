"""Tunables (spec §11): code defaults ← pi/config.json ← CLI overrides, plus the shared .env."""
from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

ENV_VARS = ("ANTHROPIC_API_KEY", "SUPABASE_URL", "SUPABASE_ANON_KEY", "CART_ID")
PATH_FIELDS = ("catalog_path", "state_dir", "gallery_dir", "model_path")


@dataclass
class Config:
    cart_id: str = "7"
    cameras: list[int | str] = field(default_factory=lambda: [0])
    width: int = 1280
    height: int = 720
    fps: int = 30
    camera_warmup_s: float = 3.0

    # motion + settle (spec §5.1)
    motion_size: tuple[int, int] = (320, 180)
    motion_thresh: int = 25
    motion_frac: float = 0.005
    settle_s: float = 1.0

    # change detection (spec §5.2)
    diff_size: tuple[int, int] = (640, 360)
    change_thresh: float = 30.0
    min_blob_frac: float = 0.004
    disturbed_frac: float = 0.60
    max_shift_px: float = 4.0
    edge_margin_px: int = 8  # full-res; a change this close to the frame edge is an arm, not an item
    empty_thresh: float = 18.0
    crop_pad: float = 0.10

    # identification (spec §6)
    features: str = "hist"  # "auto" = ONNX if downloaded; switch only after tools/gallery_check.py says it separates the props better
    local_min_score: float = 0.70
    local_min_margin: float = 0.08
    cloud_model: str = "claude-haiku-5-5"
    cloud_min_conf: float = 0.6
    cloud_timeout_s: float = 6.0  # Haiku vision + upload over a phone hotspot regularly exceeds 3 s

    # files, relative to the repo root unless absolute
    catalog_path: str = "data/store.json"
    state_dir: str = "pi/state"
    gallery_dir: str = "pi/gallery"
    model_path: str = "pi/models/features.onnx"

    roi: dict = field(default_factory=dict)  # {"0": [[x, y], ...]} normalized basket-floor polygon per camera

    server_port: int = 8080
    debug_view: bool = False

    def path(self, name: str) -> Path:
        if name not in PATH_FIELDS:
            raise KeyError(name)
        p = Path(getattr(self, name)).expanduser()
        return p if p.is_absolute() else REPO_ROOT / p


def load_config(path: Path | None = None, overrides: dict | None = None) -> Config:
    values: dict = {}
    if path is not None and Path(path).exists():
        values.update(json.loads(Path(path).read_text()))
    values.update(overrides or {})

    fields = {f.name: f for f in dataclasses.fields(Config)}
    defaults = Config()
    kwargs = {}
    for key, value in values.items():
        if key not in fields:
            log.warning("config: ignoring unknown key %r", key)
            continue
        if isinstance(getattr(defaults, key), tuple) and isinstance(value, list):
            value = tuple(value)
        kwargs[key] = value
    return Config(**kwargs)


def load_env() -> dict[str, str]:
    from dotenv import load_dotenv

    env_file = Path(os.environ.get("KART_ENV_FILE") or REPO_ROOT / ".env")
    if env_file.exists():
        load_dotenv(env_file, override=False)
    return {k: os.environ[k] for k in ENV_VARS if os.environ.get(k)}
