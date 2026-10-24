"""Synthetic two-camera cart scenes for tests and demos (no hardware needed).

A top-down "mat" (the cart floor lining) holds patterned item sprites and an optional hand.
Each camera sees it through its own fixed perspective warp, as if mounted in opposite corners
(cam1 sees the mat rotated 180°). Lighting, color cast, camera wobble and sensor noise are
applied per render. `Script` turns scene changes into timed ticks shaped like a real camera feed.
"""
from __future__ import annotations

import copy
from collections import OrderedDict
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from kartcv.sources import Frame

CAM_SIZE = (1280, 720)  # (w, h)
MAT_SIZE = (800, 500)   # (w, h), top-down mat pixels

MAT_BGR = (150, 170, 190)
WALL_BGR = 90
GRID_BGR = 60
HAND_BGR = (90, 120, 210)    # visible against the mat (lab distance 37 > change_thresh)
SLEEVE_BGR = (60, 60, 140)   # the arm: reaches the frame edge, as a real arm over the basket rim does
HAND_AXES = (70, 45)  # half of 140 × 90
ARM_WIDTH = 60

_MAT_CORNERS = np.float32([[0, 0], [MAT_SIZE[0], 0], [MAT_SIZE[0], MAT_SIZE[1]], [0, MAT_SIZE[1]]])
_QUADS = {
    0: np.float32([[260, 60], [1020, 60], [1220, 690], [60, 690]]),
    1: np.float32([[180, 110], [1100, 40], [1180, 650], [120, 700]]),
}
# cam1 is in the opposite corner: feed the mat corners rotated 180°
_H = {
    0: cv2.getPerspectiveTransform(_MAT_CORNERS, _QUADS[0]),
    1: cv2.getPerspectiveTransform(_MAT_CORNERS[[2, 3, 0, 1]], _QUADS[1]),
}


@dataclass(frozen=True)
class Item:
    item_id: str
    x: int
    y: int
    w: int = 120
    h: int = 90
    seed: int = 0
    tall: int = 0  # how far (image px) the item rises above its footprint: an upright bottle near rim height

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.w // 2, self.y + self.h // 2)


def item_sprite(seed: int, w: int, h: int) -> np.ndarray:
    hue = (seed * 47) % 180
    hsv = np.zeros((h, w, 3), np.uint8)
    hsv[:] = (hue, 200, 200)
    stripe_w = max(2, w // 12)
    for k in range(3):
        x0 = int((k + 1) * w / 4) - stripe_w // 2
        # darker stripes of the same hue: a hue+90 stripe would make seed 1 and seed 3 share a palette
        hsv[:, x0:x0 + stripe_w] = (hue, 200, 90)
    sprite = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    cv2.rectangle(sprite, (0, 0), (w - 1, h - 1), (30, 30, 30), 4)
    return sprite


def _make_mat() -> np.ndarray:
    rng = np.random.default_rng(0)
    small = rng.normal(0, 6, (MAT_SIZE[1] // 8, MAT_SIZE[0] // 8, 1)).astype(np.float32)
    tex = cv2.resize(small, MAT_SIZE, interpolation=cv2.INTER_CUBIC)[..., None]
    return np.clip(np.float32(MAT_BGR) + tex, 0, 255).astype(np.uint8)


def _make_background() -> np.ndarray:
    """What the cameras see beyond the basket floor: the cart's mesh (grid) and the room through it."""
    bg = np.full((CAM_SIZE[1], CAM_SIZE[0], 3), WALL_BGR, np.uint8)
    rng = np.random.default_rng(3)
    for _ in range(60):  # the room through the mesh: shelves, signs, people (colorful, seeded, non-repeating)
        x, y = int(rng.integers(0, CAM_SIZE[0])), int(rng.integers(0, CAM_SIZE[1]))
        w, h = int(rng.integers(30, 180)), int(rng.integers(30, 180))
        color = tuple(int(v) for v in rng.integers(0, 256, 3))
        cv2.rectangle(bg, (x, y), (x + w, y + h), color, -1)
    bg[:, ::40] = GRID_BGR
    bg[:, 1::40] = GRID_BGR
    bg[::40, :] = GRID_BGR
    bg[1::40, :] = GRID_BGR
    return bg


_MAT = _make_mat()
_BG = _make_background()
_MASK = {c: cv2.warpPerspective(np.full((MAT_SIZE[1], MAT_SIZE[0]), 255, np.uint8), _H[c], CAM_SIZE) > 0 for c in _H}
_NOISE = {c: [np.random.default_rng(1000 + 100 * c + k).normal(0, 2, (CAM_SIZE[1], CAM_SIZE[0], 3)).astype(np.int16)
              for k in range(8)] for c in _H}
_SPRITES: dict[tuple[int, int, int], np.ndarray] = {}
_CACHE: OrderedDict = OrderedDict()


def _sprite(seed: int, w: int, h: int) -> np.ndarray:
    key = (seed, w, h)
    if key not in _SPRITES:
        _SPRITES[key] = item_sprite(seed, w, h)
    return _SPRITES[key]


def _topdown(items: tuple[Item, ...], hand: tuple[int, int] | None) -> np.ndarray:
    mat = _MAT.copy()
    for it in items:
        x0, y0 = max(it.x, 0), max(it.y, 0)
        x1, y1 = min(it.x + it.w, MAT_SIZE[0]), min(it.y + it.h, MAT_SIZE[1])
        if x1 <= x0 or y1 <= y0:
            continue
        spr = _sprite(it.seed, it.w, it.h)
        mat[y0:y1, x0:x1] = spr[y0 - it.y:y1 - it.y, x0 - it.x:x1 - it.x]
    if hand is not None:
        cv2.ellipse(mat, (int(hand[0]), int(hand[1])), HAND_AXES, 0, 0, 360, HAND_BGR, -1)
    return mat


def _warped(cam: int, items: tuple[Item, ...], hand: tuple[int, int] | None, arm: bool = True,
            room_shift: tuple[int, int] = (0, 0)) -> np.ndarray:
    key = (cam, items, hand, arm, room_shift)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    view = cv2.warpPerspective(_topdown(items, hand), _H[cam], CAM_SIZE, flags=cv2.INTER_LINEAR)
    out = np.roll(_BG, (room_shift[1], room_shift[0]), axis=(0, 1)) if room_shift != (0, 0) else _BG.copy()
    out[_MASK[cam]] = view[_MASK[cam]]
    for it in items:
        if it.tall:  # its body rises in the image, over the wall and possibly to the top edge
            x, y, w, h = item_box(cam, it, pad=0.0)
            hsv = np.uint8([[[(it.seed * 47) % 180, 200, 200]]])
            color = tuple(int(v) for v in cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)[0, 0])
            cv2.rectangle(out, (x + w // 6, max(0, y - it.tall)), (x + w - w // 6, y + h // 2), color, -1)
    if hand is not None and arm:
        u, v = project(cam, hand)
        cv2.line(out, (u, v + 30), (u, CAM_SIZE[1] + ARM_WIDTH), SLEEVE_BGR, ARM_WIDTH)
    _CACHE[key] = out
    if len(_CACHE) > 64:
        _CACHE.popitem(last=False)
    return out


@dataclass
class Scene:
    items: list[Item] = field(default_factory=list)  # later items are drawn on top
    hand: tuple[int, int] | None = None              # hand center, mat coordinates
    brightness: float = 1.0
    shade: float = 0.0                               # darken the right half by up to this fraction
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0)  # per-channel BGR gain
    shift: dict[int, tuple[int, int]] = field(default_factory=dict)  # per-camera wobble/bump, px
    hidden: dict[int, set[str]] = field(default_factory=dict)        # items a camera can't see
    arm: bool = True                                                 # draw a sleeve from the hand to the frame edge
    edge_object: bool = False                                        # something static over the rim (a strap)
    room_shift: tuple[int, int] = (0, 0)                             # the room behind the mesh slides (cart rolling)

    def copy(self) -> Scene:
        return copy.deepcopy(self)

    def render(self, cam: int, noise_seed: int = 0) -> np.ndarray:
        hidden = self.hidden.get(cam, set())
        items = tuple(it for it in self.items if it.item_id not in hidden)
        hand = tuple(int(v) for v in self.hand) if self.hand is not None else None
        img = _warped(cam, items, hand, self.arm, tuple(self.room_shift))
        if self.edge_object:
            img = img.copy()
            u, v = project(cam, (MAT_SIZE[0] - 60, MAT_SIZE[1] - 60))
            cv2.line(img, (u, v), (CAM_SIZE[0], v), SLEEVE_BGR, 40)

        if self.brightness != 1.0 or self.tint != (1.0, 1.0, 1.0) or self.shade:
            f = img.astype(np.float32) * self.brightness * np.float32(self.tint)
            if self.shade:
                w = CAM_SIZE[0]
                ramp = np.ones(w, np.float32)
                x = np.arange(w // 2, w)
                t = (x - w // 2) / (w / 2)
                ramp[w // 2:] = 1.0 - self.shade * (3 * t ** 2 - 2 * t ** 3)  # smoothstep
                f *= ramp[None, :, None]
            img = np.clip(f, 0, 255).astype(np.uint8)

        dx, dy = self.shift.get(cam, (0, 0))
        if dx or dy:
            m = np.float32([[1, 0, dx], [0, 1, dy]])
            img = cv2.warpAffine(img, m, CAM_SIZE, borderMode=cv2.BORDER_REPLICATE)

        noise = _NOISE[cam][noise_seed % len(_NOISE[cam])]
        return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


def mat_roi(cam: int, inset: float = 0.01) -> list[list[float]]:
    """The basket floor as camera `cam` sees it, as a normalized polygon (the config's "roi" shape)."""
    q = _QUADS[cam]
    c = q.mean(axis=0)
    q = c + (q - c) * (1.0 - inset)
    return [[round(float(x) / CAM_SIZE[0], 4), round(float(y) / CAM_SIZE[1], 4)] for x, y in q]


def project(cam: int, xy: tuple[float, float]) -> tuple[int, int]:
    p = cv2.perspectiveTransform(np.float32([[xy]]), _H[cam])[0, 0]
    return int(round(p[0])), int(round(p[1]))


def item_box(cam: int, item: Item, pad: float = 0.10) -> tuple[int, int, int, int]:
    corners = np.float32([[[item.x, item.y], [item.x + item.w, item.y],
                           [item.x + item.w, item.y + item.h], [item.x, item.y + item.h]]])
    pts = cv2.perspectiveTransform(corners, _H[cam])[0]
    x0, y0 = pts.min(0)
    x1, y1 = pts.max(0)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    x0, y0 = max(0, int(x0 - px)), max(0, int(y0 - py))
    x1, y1 = min(CAM_SIZE[0], int(np.ceil(x1 + px))), min(CAM_SIZE[1], int(np.ceil(y1 + py)))
    return x0, y0, x1 - x0, y1 - y0


def crop_item(cam: int, item: Item, pad: float = 0.10) -> np.ndarray:
    x, y, w, h = item_box(cam, item, pad)
    return Scene(items=[item]).render(cam)[y:y + h, x:x + w].copy()


class Script:
    """Builds a tick timeline (one Frame per camera per tick) from scene changes.

    Every hand trip is 5 ticks in (the change happens on the 5th, with the hand on the spot),
    optional rest ticks, 5 ticks out (the 5th has the hand gone), then 1.5 s of stillness.
    """

    HAND_START = (-200.0, MAT_SIZE[1] / 2)

    def __init__(self, scene: Scene, hz: int = 10, cams: tuple[int, ...] = (0, 1)):
        self.scene = scene.copy()
        self.hz = hz
        self.cams = cams
        self.ticks: list[dict[int, Frame]] = []

    @property
    def t(self) -> float:
        return len(self.ticks) / self.hz

    def _emit(self) -> None:
        t, n = self.t, len(self.ticks)
        self.ticks.append({c: Frame(self.scene.render(c, noise_seed=n), t, c) for c in self.cams})

    def still(self, seconds: float) -> Script:
        for _ in range(round(seconds * self.hz)):
            self._emit()
        return self

    def _trip(self, target: tuple[float, float], on_arrival=None, rest_s: float = 0.0) -> Script:
        sx, sy = self.HAND_START
        tx, ty = target
        for i in range(1, 6):
            self.scene.hand = (sx + (tx - sx) * i / 5, sy + (ty - sy) * i / 5)
            if i == 5 and on_arrival is not None:
                on_arrival()
            self._emit()
        for _ in range(round(rest_s * self.hz)):
            self._emit()
        for j in range(1, 6):
            self.scene.hand = None if j == 5 else (tx + (sx - tx) * j / 5, ty + (sy - ty) * j / 5)
            self._emit()
        return self.still(1.5)

    def _find(self, item_id: str) -> Item:
        return next(it for it in self.scene.items if it.item_id == item_id)

    def drop(self, item: Item, linger_s: float = 0.0) -> Script:
        return self._trip(item.center, lambda: self.scene.items.append(item), rest_s=linger_s)

    def drop_many(self, items: list[Item]) -> Script:
        cx = sum(it.center[0] for it in items) / len(items)
        cy = sum(it.center[1] for it in items) / len(items)
        return self._trip((cx, cy), lambda: self.scene.items.extend(items))

    def take(self, item_id: str, linger_s: float = 0.0) -> Script:
        item = self._find(item_id)
        return self._trip(item.center, lambda: self.scene.items.remove(item), rest_s=linger_s)

    def move(self, item_id: str, dx: int, dy: int) -> Script:
        item = self._find(item_id)

        def arrive():
            i = self.scene.items.index(item)
            self.scene.items[i] = replace(item, x=item.x + dx, y=item.y + dy)

        return self._trip(item.center, arrive)

    def hand_pass(self) -> Script:
        return self._trip((MAT_SIZE[0] / 2, MAT_SIZE[1] / 2))

    def hand_rest(self, seconds: float) -> Script:
        return self._trip((MAT_SIZE[0] / 2, MAT_SIZE[1] / 2), rest_s=seconds)

    def set(self, **scene_fields) -> Script:
        for k, v in scene_fields.items():
            if not hasattr(self.scene, k):
                raise AttributeError(k)
            setattr(self.scene, k, copy.deepcopy(v))
        return self.still(1.5)
