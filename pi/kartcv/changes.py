"""Per-camera change detection between two settled frames (spec §5.2)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from kartcv.roi import gray_outside, polygon_mask

_OPEN = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
_CLOSE = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))


def lab_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-pixel color distance in 8-bit LAB, with lightness weighted half (shadows matter less)."""
    d = cv2.cvtColor(a, cv2.COLOR_BGR2LAB).astype(np.float32) - cv2.cvtColor(b, cv2.COLOR_BGR2LAB).astype(np.float32)
    d[..., 0] *= 0.5
    return np.sqrt((d * d).sum(axis=2))


def match_gain(img: np.ndarray, target: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Scale each BGR channel of `img` so its median matches `target`'s.

    Cancels global brightness and white-balance shifts (the Brio's auto white balance moves when a
    big colored item enters the frame). Medians are dominated by the mat, so items don't skew it.
    """
    sel = mask.astype(bool) if mask is not None and mask.any() else slice(None)
    m_img = np.median(img[sel].reshape(-1, 3), axis=0).astype(np.float32)
    m_tgt = np.median(target[sel].reshape(-1, 3), axis=0).astype(np.float32)
    gain = np.where(m_img >= 1.0, m_tgt / np.maximum(m_img, 1.0), 1.0).astype(np.float32)
    return np.clip(img.astype(np.float32) * gain, 0, 255).astype(np.uint8)


def translate(img: np.ndarray, dx: float, dy: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


@dataclass
class Blob:
    """A changed region. `before`/`after` are padded crops (context for Claude and for people);
    `core` is the unpadded changed box inside them, which is what fingerprints are taken from,
    so whatever surrounds the item (mat, or another grocery under it) doesn't skew the match."""

    cam: int
    box: tuple[int, int, int, int]  # x, y, w, h in full-res pixels, padded and clipped
    area_frac: float
    before: np.ndarray
    after: np.ndarray
    core: tuple[int, int, int, int] = (0, 0, 0, 0)  # x, y, w, h inside the crops; zero size = whole crop
    edge: bool = False  # part of a change that reaches the image edge: an arm over the rim, a strap

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


def detect_changes(cam: int, reference: np.ndarray, current: np.ndarray, cfg, roi=None) -> ChangeResult:
    """Compare two still frames. `roi` (normalized floor polygon) limits everything to the basket floor."""
    w, h = cfg.diff_size
    full_h, full_w = current.shape[:2]
    sx, sy = full_w / w, full_h / h
    ref_s = cv2.resize(reference, (w, h), interpolation=cv2.INTER_AREA)
    cur_s = cv2.resize(current, (w, h), interpolation=cv2.INTER_AREA)

    def result(status, blobs=(), frac=0.0, shift=(0.0, 0.0)):
        return ChangeResult(cam, status, list(blobs), frac, shift, current, reference)

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
        return result("disturbed", shift=shift)

    # 2. Brightness-normalized color difference, cleaned up.
    cur_s = match_gain(cur_s, ref_s, m)
    dist = lab_distance(cv2.GaussianBlur(ref_s, (7, 7), 0), cv2.GaussianBlur(cur_s, (7, 7), 0))
    mask = (dist > cfg.change_thresh).astype(np.uint8) * 255
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

    # 3. Solid blobs only (inside the floor).
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
        edge = bool(reaching_edge) and bool(reaching_edge & set(np.unique(full_labels[labels == i])))
        blobs.append(Blob(cam, (x0, y0, x1 - x0, y1 - y0), area / (w * h),
                          gray_outside(reference[y0:y1, x0:x1], mc), gray_outside(current[y0:y1, x0:x1], mc),
                          (cx0 - x0, cy0 - y0, cx1 - cx0, cy1 - cy0), edge))
    if not blobs:
        return result("none", frac=frac, shift=shift)
    return result("blobs", blobs, frac, shift)
