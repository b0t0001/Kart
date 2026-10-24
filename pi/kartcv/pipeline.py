"""The main loop, one tick at a time: motion → settle → changes → decisions → cart memory → events.

Live cameras, recordings and synthetic scripts all feed the same `step(tick)`, so whatever the tests
prove about a script holds for a replayed recording and for the real cart.
"""
from __future__ import annotations

import logging
import math
import threading
from collections import deque
from pathlib import Path

import cv2
import numpy as np

from kartcv.cart import CartMemory
from kartcv.changes import detect_changes
from kartcv.decide import Decision, apply_decision, decide
from kartcv.events import Event
from kartcv.motion import MotionDetector, SettleTracker
from kartcv.roi import draw_outline

log = logging.getLogger(__name__)


class Pipeline:
    def __init__(self, cfg, cams: list[int], identifier, features, sinks: list, state_dir: Path):
        self.cfg = cfg
        self.cams = list(cams)
        self.identifier = identifier
        self.features = features
        self.sinks = sinks
        self.state_dir = Path(state_dir)
        self.crops_dir = self.state_dir / "crops"
        self.crops_dir.mkdir(parents=True, exist_ok=True)
        self.cart = CartMemory.load(self.state_dir / "cart.json")
        self.empties: dict[int, np.ndarray] = {}
        for c in self.cams:
            p = self._empty_path(c)
            if p.exists():
                img = cv2.imread(str(p), cv2.IMREAD_COLOR)
                if img is not None:
                    self.empties[c] = img
        self.references: dict[int, np.ndarray] = {}
        self.apply_roi()
        self.settle = SettleTracker(cfg.settle_s)
        self.last_decisions: list[Decision] = []
        self._reset_requested = threading.Event()
        self._lock = threading.Lock()
        self._latest: dict[int, object] = {}
        self._last_events: deque = deque(maxlen=10)
        self._first_run = not self.empties
        self._present: set[int] = set()  # cameras that had a frame on the previous tick
        self._resync: set[int] = set()   # cameras back from an outage: re-reference at the next settle
        self.camera_moved: set[int] = set()  # a big view shift with items in the cart: reset recommended
        self._recheck_at: float | None = None  # when to re-judge a deferred edge-touching change, if still

    def _roi(self, cam: int):
        return self.cfg.roi.get(str(cam))

    def apply_roi(self) -> None:
        """(Re)build the per-camera motion detectors from cfg.roi."""
        self.motion = {c: MotionDetector(self.cfg.motion_size, self.cfg.motion_thresh, self.cfg.motion_frac,
                                         roi=self._roi(c)) for c in self.cams}

    def _empty_path(self, cam: int) -> Path:
        return self.state_dir / f"empty_cam{cam}.jpg"

    # --- control (thread-safe) ---
    def request_reset(self) -> None:
        self._reset_requested.set()

    def status(self) -> dict:
        with self._lock:
            cams = {c: {"last_ts": (self._latest[c].ts if c in self._latest else None)} for c in self.cams}
            events = list(self._last_events)
        return {"state": "settling" if self.settle.state == "motion" else "watching",
                "cameras": cams, "items": len(self.cart.instances), "last_events": events,
                "camera_moved": sorted(self.camera_moved)}

    def latest_frames(self, overlay: bool = False) -> dict[int, np.ndarray]:
        with self._lock:
            frames = {c: f.image for c, f in self._latest.items()}
        if overlay:  # debug page: outline each camera's basket-floor ROI
            frames = {c: draw_outline(img, self._roi(c)) for c, img in frames.items()}
        return frames

    # --- the loop ---
    def _reset(self, frames: dict) -> None:
        self.empties = {}
        for c in self.cams:
            self._empty_path(c).unlink(missing_ok=True)
        for c, f in frames.items():
            self._set_empty(c, f.image)
            self.references[c] = f.image
            self.motion[c].reset()
        self.settle.reset()
        self.cart.clear()
        self.camera_moved.clear()
        self._resync.difference_update(frames)
        self._reset_requested.clear()

    def _set_empty(self, cam: int, image: np.ndarray) -> None:
        self.empties[cam] = image
        cv2.imwrite(str(self._empty_path(cam)), image, [cv2.IMWRITE_JPEG_QUALITY, 95])

    def step(self, tick: dict) -> list[Event]:
        self.last_decisions = []
        frames = {c: f for c, f in tick.items() if c in self.cams and f is not None}
        # A camera back from an outage has a stale reference: whatever happened meanwhile would be
        # billed again. It sits out one settle and takes that still frame as its new reference.
        for c in frames.keys() - self._present:
            if c in self.references:
                log.warning("cam%d is back: re-syncing it at the next settle", c)
                self._resync.add(c)
                self.motion[c].reset()
        self._present = set(frames)
        if not frames:
            return []
        with self._lock:
            self._latest.update(frames)

        if self._reset_requested.is_set() or not self.empties:
            if self._first_run and not self._reset_requested.is_set():
                log.warning("first run: treating the current view as the EMPTY basket (cart must be empty)")
            else:
                log.info("reset: cart memory cleared, new empty-basket pictures taken")
            self._first_run = False
            self._reset(frames)
            return []
        for c, f in frames.items():
            if c not in self.empties and not self.cart.instances:
                self._set_empty(c, f.image)  # a camera that came up late, while the cart is still empty
            self.references.setdefault(c, f.image)

        moving = {c: self.motion[c].update(f.image) for c, f in frames.items()}
        ts = min(f.ts for f in frames.values())
        was = self.settle.state
        settled = self.settle.update(ts, moving)
        if any(moving.values()):
            self._recheck_at = None  # it moved: not a static object; the next settle judges it again
        if was == "idle" and self.settle.state == "motion":
            log.info("MOTION")
        if settled:
            log.info("SETTLED")
            return self._process(frames, ts, accept_edges=False)
        if self._recheck_at is not None and self.settle.state == "idle" and ts >= self._recheck_at - 1e-6:
            self._recheck_at = None
            log.info("RECHECK: the edge-touching change stayed still %.0f s more: judging it as an item",
                     self.cfg.intrusion_recheck_s)
            return self._process(frames, ts, accept_edges=True)
        return []

    def _process(self, frames: dict, ts: float, accept_edges: bool) -> list[Event]:
        """Judge a still moment. Changes reaching the image edge (an arm over the rim, or a tall item
        poking up past it) are deferred unless `accept_edges`: an arm moves on, a bottle stays, so if
        nothing moves for intrusion_recheck_s the change is re-judged with accept_edges=True."""
        results = []
        edge_cams = set()
        for c, f in frames.items():
            if c in self._resync:
                self.references[c] = f.image
                self._resync.discard(c)
                continue
            old_ref = self.references[c]
            r = detect_changes(c, old_ref, f.image, self.cfg, roi=self._roi(c))
            scale = f.image.shape[1] / self.cfg.diff_size[0]
            new_ref = f.image
            if r.moved:
                # Never re-align memory to an estimated shift: on a real cart the estimate can lock onto
                # the room. Bill nothing; if a camera was really knocked, an empty-cart reset fixes it.
                log.warning("cam%d view shifted by (%.0f, %.0f) px (camera knocked?): no events this settle; "
                            "if it really moved, empty the cart and reset", c, *r.shift)
                if self.cart.instances:
                    # Keep the old reference: if this was a false alarm, the next settle re-judges against
                    # the true before-picture; if the camera really moved, it stays flagged until a reset.
                    self.camera_moved.add(c)
                    new_ref = old_ref
            elif r.status == "disturbed":
                log.warning("cam%d: %.0f%% of the view changed (lighting?); ignoring this settle", c, 100 * r.changed_frac)
            elif r.status == "blobs" and not accept_edges:
                # Something reaching the image edge: an arm over the rim, or a tall item poking up past it.
                # Defer it, keeping the old reference under it, so that whatever an arm put down, took or
                # covered is judged against the true before-picture once it leaves.
                edge = [b for b in r.blobs if b.edge]
                if edge:
                    log.info("INTRUSION: cam%d sees something reaching the edge (an arm? a tall item?); "
                             "waiting %.0f s for it to leave or stay", c, self.cfg.intrusion_recheck_s)
                    edge_cams.add(c)
                    new_ref = f.image.copy()
                    for b in edge:
                        x, y, w, h = b.box
                        new_ref[y:y + h, x:x + w] = old_ref[y:y + h, x:x + w]
                    r.blobs = [b for b in r.blobs if b not in edge]
                    if not r.blobs:
                        r.status = "none"
            self.references[c] = new_ref
            results.append(r)
        if edge_cams:
            self._recheck_at = ts + self.cfg.intrusion_recheck_s
        if not self.cart.instances:
            # Nothing in the cart and nothing new: this is a fresh empty-basket picture (tracks light drift).
            for r in results:
                if r.cam in edge_cams:
                    continue
                if r.status in ("none", "disturbed"):
                    self._set_empty(r.cam, r.frame)
                    self.camera_moved.discard(r.cam)

        decisions = decide(results, self.empties, self.cart, self.identifier, self.features, self.cfg)
        self.last_decisions = decisions
        events = []
        for d in decisions:
            if d.kind == "moved":
                apply_decision(self.cart, d)
                continue
            ev = Event.new(cart_id=self.cfg.cart_id, type=d.kind, product_id=d.product_id,
                           confidence=round(float(d.confidence), 3), method=d.method, label=d.label,
                           cameras=list(d.cameras), crops=[])
            if d.kind == "removed" and d.product_id is None:
                inst = self.cart.instances.get(d.instance_id)
                ev.resolves_event_id = (inst.event_id or None) if inst else None
            for b in d.blobs:
                name = f"{ev.event_id}_cam{b.cam}.jpg"
                cv2.imwrite(str(self.crops_dir / name), b.after if d.kind == "added" else b.before)
                rel = f"{self.state_dir.name}/crops/{name}"
                ev.crops.append(rel)
                if b.cam in d.views:
                    d.views[b.cam].crop_path = rel
            # Queue the event (outbox) before changing memory: if the process dies in between, the
            # backend still gets the event and memory catches up on the next settle, not the reverse.
            for s in self.sinks:
                try:
                    s.send(ev)
                except Exception:  # one broken sink must not stop the cart
                    log.exception("sink %s failed", type(s).__name__)
            inst = apply_decision(self.cart, d)
            if d.kind == "added" and inst is not None:
                self.cart.set_event_id(inst.instance_id, ev.event_id)
            with self._lock:
                self._last_events.append(ev.to_json())
            events.append(ev)
        return events
