"""Per-camera change detection between two settled frames (spec §5.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from kartcv.roi import gray_outside, polygon_mask

_OPEN = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_CLOSE = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
LENS_COVERED = 0.3  # the floor kept under this share of its texture: something right in front of the lens
RAISE_MAX = 2.0  # an identification box rises at most this many times its own height above the floor box
BODY_SOLID = 0.5  # ...through rows where at least this share of the item's own columns changed


def work_size(shape, base: tuple[int, int]) -> tuple[int, int]:
    """The (w, h) to compare a frame at: the configured landscape size, turned for portrait frames."""
    w, h = int(base[0]), int(base[1])
    return (min(w, h), max(w, h)) if shape[0] > shape[1] else (max(w, h), min(w, h))


def lab_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-pixel color distance in 8-bit LAB, with lightness weighted half (shadows matter less)."""
    d = cv2.cvtColor(a, cv2.COLOR_BGR2LAB).astype(np.float32) - cv2.cvtColor(b, cv2.COLOR_BGR2LAB).astype(np.float32)
    d[..., 0] *= 0.5
    return np.sqrt((d * d).sum(axis=2))


def lighting_only(ref: np.ndarray, cur: np.ndarray, chroma: float, structure: float) -> np.ndarray:
    """Pixels whose change is just light or shadow: same color (Δab small) and the same texture showing
    through, only brighter or darker. Measured on the real cart: sun stripes and shadows Δab ≈ 4–5,
    texture ≈ 2; items Δab 18–47 (a printed label also changes texture ≈ 20)."""
    lr = cv2.cvtColor(cv2.GaussianBlur(ref, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    lc = cv2.cvtColor(cv2.GaussianBlur(cur, (5, 5), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    dab = np.hypot(lc[..., 1] - lr[..., 1], lc[..., 2] - lr[..., 2])
    gr = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gc = cv2.cvtColor(cur, cv2.COLOR_BGR2GRAY).astype(np.float32)
    br, bc = cv2.GaussianBlur(gr, (0, 0), 5), cv2.GaussianBlur(gc, (0, 0), 5)
    texture = cv2.GaussianBlur(np.abs((gc - bc) - (bc / np.maximum(br, 1.0)) * (gr - br)), (5, 5), 0)
    return (dab < chroma) & (texture < structure)


def match_gain(img: np.ndarray, target: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Scale each BGR channel of `img` so its median matches `target`'s.

    Cancels global brightness and white-balance shifts (the Brio's auto white balance moves when a
    big colored item enters the frame). Medians are dominated by the mat, so items don't skew it.
    """
    step = 4 if img.shape[0] * img.shape[1] > 200_000 else 1  # medians from a sample: same answer, 16x cheaper
    img_s, tgt_s = img[::step, ::step], target[::step, ::step]
    mask_s = mask[::step, ::step] if mask is not None else None
    sel = mask_s.astype(bool) if mask_s is not None and mask_s.any() else slice(None)
    m_img = np.median(img_s[sel].reshape(-1, 3), axis=0).astype(np.float32)
    m_tgt = np.median(tgt_s[sel].reshape(-1, 3), axis=0).astype(np.float32)
    gain = np.where(m_img >= 1.0, m_tgt / np.maximum(m_img, 1.0), 1.0).astype(np.float32)
    return np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def translate(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


@dataclass
class Blob:
    """A changed region. `before`/`after` are padded crops of the floor (gray outside it); `core` is
    the unpadded changed box inside them, which is what fingerprints are taken from, so whatever
    surrounds the item (mat, or another grocery under it) doesn't skew the match. `ident` is what
    Claude and the shopper see of it: the unmasked frame over `box` raised over the item's own body,
    where it rises past the floor (a tall bag in front of the mesh)."""

    cam: int
    box: tuple[int, int, int, int]  # x, y, w, h in full-res pixels, padded and clipped
    area_frac: float
    before: np.ndarray
    after: np.ndarray
    core: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h inside the crops; zero size = whole crop
    edge: bool = False  # part of a change that reaches the image edge: an arm over the rim, a strap
    ident: np.ndarray | None = None
    ident_box: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h in full-res pixels
    placement: str = ""  # the hand-in it started in, if it waited on an intrusion across a later one

    @property
    def ident_crop(self) -> np.ndarray:
        return self.ident if self.ident is not None else self.after

    def _core(self, crop: np.ndarray) -> np.ndarray:
        x, y, w, h = self.core
        return crop[y:y + h, x:x + w] if w > 0 and h > 0 else crop

    @property
    def core_box(self) -> tuple[int, int, int, int]:
        """The unpadded changed box in full-res frame pixels."""
        x, y, w, h = self.core
        if w <= 0 or h <= 0:
            return self.box
        return (self.box[0] + x, self.box[1] + y, w, h)

    @property
    def before_core(self) -> np.ndarray:
        return self._core(self.before)

    @property
    def after_core(self) -> np.ndarray:
        return self._core(self.after)


@dataclass
class ChangeResult:
    cam: int
    status: str  # "none" | "disturbed" | "blobs"
    blobs: list[Blob] = field(default_factory=list)
    changed_frac: float = 0.0
    shift: tuple[float, float] = (0.0, 0.0)  # camera shift, full-res px (+x = content moved right)
    frame: np.ndarray | None = None
    reference: np.ndarray | None = None
    moved: bool = False  # the whole view shifted (verified): the camera itself moved
    deferred: list = field(default_factory=list)  # boxes held back this settle (edge-touching: arm or tall item)


def _texture(img: np.ndarray, floor: np.ndarray) -> float:
    lap = np.abs(cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.CV_32F))
    return float(lap[floor].mean()) if floor.any() else float(lap.mean())


def floor_texture(image: np.ndarray, cfg, roi=None) -> float:
    """How much fine detail the floor shows (at the comparison size): the bare basket's, for the lens test."""
    w, h = work_size(image.shape, cfg.diff_size)
    m = polygon_mask(roi, (w, h))
    return _texture(cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA),
                    m.astype(bool) if m is not None else np.ones((h, w), bool))


def detect_changes(cam: int, reference: np.ndarray, current: np.ndarray, cfg, roi=None,
                   bare_texture: float | None = None) -> ChangeResult:
    """Compare two still frames. `roi` (normalized floor polygon) limits everything to the basket floor.
    `bare_texture` (floor_texture of the empty basket) lets it tell a covered lens from an emptied cart."""
    w, h = work_size(current.shape, cfg.diff_size)
    full_h, full_w = current.shape[:2]
    sx, sy = full_w / w, full_h / h
    ref_s = cv2.resize(reference, (w, h), interpolation=cv2.INTER_AREA)
    cur_s = cv2.resize(current, (w, h), interpolation=cv2.INTER_AREA)

    def result(status, blobs=(), frac=0.0, shift=(0.0, 0.0), moved=False):
        return ChangeResult(cam, status, list(blobs), frac, shift, current, reference, moved)

    def changed(a, b, valid):
        """Share of `valid` floor pixels that differ between a and b (b gain-matched to a)."""
        d = lab_distance(cv2.GaussianBlur(a, (7, 7), 0), cv2.GaussianBlur(match_gain(b, a, valid), (7, 7), 0))
        return float(((d > cfg.change_thresh) & valid).sum()) / max(1, int(valid.sum()))

    m = polygon_mask(roi, (w, h))
    floor = m.astype(bool) if m is not None else np.ones((h, w), bool)

    # 1. Did the camera itself move (bumped)? Then nothing can be compared pixel by pixel. Only the
    # floor votes: the room seen through the mesh slides by whenever the cart rolls.
    g_ref = cv2.cvtColor(ref_s, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g_cur = cv2.cvtColor(cur_s, cv2.COLOR_BGR2GRAY).astype(np.float32)
    window = cv2.createHanningWindow((w, h), cv2.CV_32F)
    if m is not None:
        window = window * cv2.GaussianBlur(m.astype(np.float32), (31, 31), 0)
    (dx, dy), _ = cv2.phaseCorrelate(g_ref, g_cur, window)
    shift = (dx * sx, dy * sy)
    if math.hypot(dx, dy) > cfg.max_shift_px:
        # Verify before believing it: a big new object (a printed label) can win the correlation. If the
        # camera really moved, shifting the reference by the estimate explains most of the change.
        mx, my = int(math.ceil(abs(dx))) + 2, int(math.ceil(abs(dy))) + 2
        valid = floor.copy()
        valid[:my, :] = valid[-my:, :] = False
        valid[:, :mx] = valid[:, -mx:] = False
        plain = changed(ref_s, cur_s, valid)
        aligned = changed(translate(ref_s, dx, dy), cur_s, valid)
        if plain >= 0.02 and aligned < 0.5 * plain:  # a real move leaves lots to explain, and explains it
            return result("disturbed", frac=plain, shift=shift, moved=True)
        shift = (0.0, 0.0)  # not a camera move: compare the frames as they are

    # 2. Something right in front of the lens (an arm passing close to cam0) blurs the whole view flat:
    # brightness matching would make it pass for bare floor and every item under it look gone. Flatter
    # than even the bare basket is (lifting a printed box out only gets it back to that).
    base = _texture(ref_s, floor) if bare_texture is None else min(_texture(ref_s, floor), bare_texture)
    if _texture(cur_s, floor) < LENS_COVERED * max(base, 1e-6):
        return result("disturbed", frac=1.0, shift=shift)

    # 3. Brightness-normalized color difference, cleaned up. Gain comes from the floor that didn't
    # change: a big colored item would otherwise skew the medians and make bare floor look "changed".
    ref_b = cv2.GaussianBlur(ref_s, (7, 7), 0)
    dist = lab_distance(ref_b, cv2.GaussianBlur(match_gain(cur_s, ref_s, m), (7, 7), 0))
    rough = cv2.dilate((dist > cfg.change_thresh).astype(np.uint8), _CLOSE)
    steady = floor & (rough == 0)
    cur_m = match_gain(cur_s, ref_s, steady.astype(np.uint8) if steady.sum() > 0.05 * floor.sum() else m)
    dist = lab_distance(ref_b, cv2.GaussianBlur(cur_m, (7, 7), 0))
    # Light and shadow (sun through blinds, an item's long shadow) change brightness, not the surface.
    light = lighting_only(ref_s, cur_m, cfg.lighting_chroma, cfg.lighting_structure)
    mask = ((dist > cfg.change_thresh) & ~light).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, _OPEN)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, _CLOSE)
    full = mask > 0
    inside = (full & floor).astype(np.uint8)
    frac = float(inside.sum()) / max(1, int(floor.sum()))
    if frac > cfg.disturbed_frac:
        return result("disturbed", frac=frac, shift=shift)

    # An in-floor change that connects, through changed pixels, to the image edge comes from outside
    # the view: an arm over the rim. A tall item leaning on the wall rises over the mesh but doesn't
    # reach the image edge, so it stays an item.
    band = max(2, int(round(cfg.edge_margin_px / sx)))
    _, full_labels = cv2.connectedComponents(full.astype(np.uint8))
    border = np.zeros_like(full)
    border[:band, :] = border[-band:, :] = True
    border[:, :band] = border[:, -band:] = True
    reaching_edge = set(np.unique(full_labels[border & full])) - {0}
    full_mask = polygon_mask(roi, (full_w, full_h))

    # 4. Solid blobs only (inside the floor).
    n, labels, stats, _ = cv2.connectedComponentsWithStats(inside)
    min_area = cfg.min_blob_frac * w * h
    blobs = []
    for i in range(1, n):
        bx, by, bw, bh, area = stats[i]
        if area < min_area:
            continue
        cx0, cy0 = int(bx * sx), int(by * sy)
        cx1, cy1 = min(full_w, int(math.ceil((bx + bw) * sx))), min(full_h, int(math.ceil((by + bh) * sy)))
        px, py = (cx1 - cx0) * cfg.crop_pad, (cy1 - cy0) * cfg.crop_pad
        x0, y0 = max(0, int(cx0 - px)), max(0, int(cy0 - py))
        x1, y1 = min(full_w, int(math.ceil(cx1 + px))), min(full_h, int(math.ceil(cy1 + py)))
        mc = full_mask[y0:y1, x0:x1] if full_mask is not None else None
        comps = set(np.unique(full_labels[labels == i])) - {0}
        edge = bool(reaching_edge & comps)
        # Identification gets the item, not a floor cutout: where the item leaves the floor at its top,
        # the box rises over its body for as long as the body stays solid in those columns (changed and
        # connected to this blob). A passer-by seen through the mesh behind it is patchy, not a solid
        # column, and the rise is capped, so no more of the room than the item covers goes to Claude.
        top = y0
        if comps and by > 0:
            neck = np.nonzero((labels[by:by + max(2, bh // 10), bx:bx + bw] == i).any(axis=0))[0] + bx
            solid = np.isin(full_labels[:by, neck], list(comps)).mean(axis=1) >= BODY_SOLID
            gaps = np.nonzero(~solid)[0]
            body_top = gaps[-1] + 1 if gaps.size else 0  # the topmost row of the solid run above the blob
            if body_top < by:
                top = min(y0, max(0, int(body_top * sy - py), int(y0 - RAISE_MAX * (y1 - y0))))
        blobs.append(Blob(cam, (x0, y0, x1 - x0, y1 - y0), area / (w * h),
                          gray_outside(reference[y0:y1, x0:x1], mc), gray_outside(current[y0:y1, x0:x1], mc),
                          (cx0 - x0, cy0 - y0, cx1 - cx0, cy1 - cy0), edge,
                          current[top:y1, x0:x1].copy(), (x0, top, x1 - x0, y1 - top)))
    if not blobs:
        return result("none", frac=frac, shift=shift)
    return result("blobs", blobs, frac, shift)
