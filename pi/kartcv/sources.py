"""Frame sources behind one shape: live cameras, recordings on disk, and in-memory lists (tests)."""
from __future__ import annotations

import glob
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import cv2
import numpy as np

log = logging.getLogger(__name__)

REOPEN_EVERY_S = 5.0
STALE_AFTER_S = 2.0


@dataclass
class Frame:
    image: np.ndarray  # BGR uint8
    ts: float
    cam: int


Tick = dict  # dict[int, Frame | None]: one frame (or None) per camera for one loop step


def camera_paths(paths: list[str] | None = None, realpath=os.path.realpath) -> list[str]:
    """One stable /dev/v4l/by-path node per USB camera, ordered by USB port.

    udev adds both a usb- and a usbv2- link for each camera; keep the first (usb-). Non-USB video
    nodes (the Pi's mailbox codec) are left out.
    """
    if paths is None:
        paths = glob.glob("/dev/v4l/by-path/*usb*-video-index0")
    seen, cams = set(), []
    for p in sorted(paths):
        if "usb" not in os.path.basename(p) or not p.endswith("-video-index0"):
            continue
        real = realpath(p)
        if real not in seen:
            seen.add(real)
            cams.append(p)
    return cams


def _default_capture(source: int | str):
    if sys.platform.startswith("linux"):
        return cv2.VideoCapture(source, cv2.CAP_V4L2)
    return cv2.VideoCapture(source)


class LiveCamera:
    """Grabs continuously on a daemon thread and keeps only the latest frame.

    Never sets CAP_PROP_BUFFERSIZE: on the Pi's V4L2 driver it halves the frame rate.
    Frames from the first `warmup_s` after each (re)open are withheld while auto exposure settles.
    """

    def __init__(self, cam: int, source: int | str, width: int, height: int, fps: int,
                 warmup_s: float = 3.0, capture_factory: Callable | None = None):
        self.cam = cam
        self.source = source
        self.width, self.height, self.fps = width, height, fps
        self.warmup_s = warmup_s
        self._factory = capture_factory or _default_capture
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._latest_mono = 0.0
        self._opened_mono = 0.0
        self._stop = threading.Event()
        self.healthy = False
        self._thread = threading.Thread(target=self._run, name=f"cam{cam}", daemon=True)
        self._thread.start()

    def _open(self):
        cap = self._factory(self.source)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        return cap

    def _run(self) -> None:
        while not self._stop.is_set():
            cap = self._open()
            if cap is None:
                self.healthy = False
                log.warning("cam%d: could not open %s, retrying in %.0f s", self.cam, self.source, REOPEN_EVERY_S)
                self._stop.wait(REOPEN_EVERY_S)
                continue
            with self._lock:
                self._opened_mono = time.monotonic()
                self._latest = None
            last_ok = time.monotonic()
            while not self._stop.is_set():
                ok, image = cap.read()
                now = time.monotonic()
                if ok and image is not None:
                    last_ok = now
                    self.healthy = True
                    with self._lock:
                        self._latest = Frame(image, time.time(), self.cam)
                        self._latest_mono = now
                elif now - last_ok > STALE_AFTER_S:
                    log.warning("cam%d: no frames for %.0f s, reopening", self.cam, STALE_AFTER_S)
                    break
            cap.release()
            self.healthy = False
            if not self._stop.is_set():
                self._stop.wait(REOPEN_EVERY_S)

    def read(self) -> Frame | None:
        now = time.monotonic()
        with self._lock:
            if self._latest is None:
                return None
            if now - self._opened_mono < self.warmup_s or now - self._latest_mono > STALE_AFTER_S:
                return None
            return self._latest

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


class FrameListSource:
    """Replays frames in order, then returns None. Frames can be in memory or loaded lazily from disk."""

    def __init__(self, cam: int, frames: list[Frame] | None = None, paths: list[tuple[float, Path]] | None = None):
        self.cam = cam
        self._frames = frames
        self._paths = paths or []
        self._i = 0

    def __len__(self) -> int:
        return len(self._frames) if self._frames is not None else len(self._paths)

    @property
    def exhausted(self) -> bool:
        return self._i >= len(self)

    def read(self) -> Frame | None:
        if self.exhausted:
            return None
        i, self._i = self._i, self._i + 1
        if self._frames is not None:
            return self._frames[i]
        ts, path = self._paths[i]
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        return Frame(image, ts, self.cam) if image is not None else None


def save_tick(root: Path, tick: Tick) -> None:
    for cam, frame in tick.items():
        if frame is None:
            continue
        d = Path(root) / f"cam{cam}"
        d.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(d / f"{round(frame.ts * 1000):013d}.jpg"), frame.image)


def load_recording(root: Path) -> list[FrameListSource]:
    sources = []
    cam_dirs = sorted((d for d in Path(root).glob("cam*") if d.is_dir() and d.name[3:].isdigit()),
                      key=lambda d: int(d.name[3:]))
    for d in cam_dirs:
        paths = sorted(d.glob("*.jpg"))
        sources.append(FrameListSource(int(d.name[3:]), paths=[(int(p.stem) / 1000.0, p) for p in paths]))
    return sources


def iter_ticks(sources: list[FrameListSource]) -> Iterator[Tick]:
    while not all(s.exhausted for s in sources):
        yield {s.cam: s.read() for s in sources}


def snap_all(cfg, out_dir: Path, timeout_s: float = 5.0) -> dict[int, Path | None]:
    """Open every configured camera at once, wait out the exposure warm-up, save one frame each."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cams = [LiveCamera(k, src, cfg.width, cfg.height, cfg.fps, warmup_s=cfg.camera_warmup_s)
            for k, src in enumerate(cfg.cameras)]
    deadline = time.monotonic() + cfg.camera_warmup_s + timeout_s
    result: dict[int, Path | None] = {c.cam: None for c in cams}
    try:
        while time.monotonic() < deadline and any(v is None for v in result.values()):
            for c in cams:
                if result[c.cam] is None:
                    frame = c.read()
                    if frame is not None:
                        path = out_dir / f"cam{c.cam}.jpg"
                        cv2.imwrite(str(path), frame.image)
                        result[c.cam] = path
            time.sleep(0.05)
    finally:
        for c in cams:
            c.close()
    return result
