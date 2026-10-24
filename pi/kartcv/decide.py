"""Turn per-camera change blobs into cart decisions (spec §5.3, §5.4, §6.2).

Each blob is classified added/removed against the empty-basket picture and cart memory. The two
cameras are then combined into one decision per physical unit: a product's count changes by the most
units any single camera saw. Added units are identified (gallery, then Claude); removed units are
matched only against what the cart remembers. Same-product add+remove in one settle is a move.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import logging

import numpy as np

from kartcv.cart import CartMemory, Instance, View
from kartcv.changes import Blob, ChangeResult, lab_distance, match_gain
from kartcv.roi import polygon_mask

log = logging.getLogger(__name__)

IOU_OVERLAP = 0.1
IOU_WEIGHT = 0.2
VANISHED_COVERAGE = 0.6  # a remembered unit whose box is this much inside an emptied spot is gone


@dataclass
class Decision:
    kind: str  # "added" | "removed" | "moved"
    product_id: str | None
    confidence: float
    method: str  # "local" | "cloud" | "memory" | "none"
    label: str
    cameras: list[int] = field(default_factory=list)
    blobs: list[Blob] = field(default_factory=list)
    views: dict[int, View] = field(default_factory=dict)  # after-crop fingerprints (added / moved)
    instance_id: str | None = None                       # removed / moved
    awaiting: dict[int, list] = field(default_factory=dict)  # added: cameras whose view was held back
    count: int = 1  # added: identical units in this blob (claude_count beta); one event and one unit each


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def _sim(a, b) -> float:
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    if a.shape != b.shape:  # fingerprints from a different feature extractor (e.g. hist vs ONNX)
        return 0.0
    return float(a @ b)


def _crop(img: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    return img[y:y + h, x:x + w]


def gain_matched(result: ChangeResult, empty: np.ndarray, roi=None, cart: CartMemory | None = None):
    """(current, reference, floor mask) brightness-matched to the empty picture. The gain comes from bare
    floor only: the ROI minus every remembered item's box and every change, so a big colored item can't
    skew the colors. Full-frame work: once per camera."""
    h, w = empty.shape[:2]
    m = polygon_mask(roi, (w, h))
    bare = (m.copy() if m is not None else np.ones((h, w), np.uint8))
    for x, y, bw, bh in [b.box for b in result.blobs] + ([v.box for _, v in cart.views_in(result.cam)] if cart else []):
        bare[max(0, y):y + bh, max(0, x):x + bw] = 0
    floor_px = int(m.sum()) if m is not None else w * h
    gm = bare if bare.sum() > 0.05 * floor_px else m
    return match_gain(result.frame, empty, gm), match_gain(result.reference, empty, gm), m


def _mean(d: np.ndarray, m: np.ndarray | None) -> float:
    if m is not None and m.any():
        return float(d[m.astype(bool)].mean())
    return float(d.mean())


def classify_blob(blob: Blob, result: ChangeResult, empty: np.ndarray, cart: CartMemory, features, cfg,
                  matched: tuple | None = None) -> str | None:
    cur, ref, m = matched if matched is not None else gain_matched(result, empty, cfg.roi.get(str(blob.cam)), cart)
    empty_crop = _crop(empty, blob.box)
    after = _crop(cur, blob.box)
    before = _crop(ref, blob.box)
    mc = _crop(m, blob.box) if m is not None else None  # judge the floor only, not the room behind it
    after_empty = _mean(lab_distance(after, empty_crop), mc) < cfg.empty_thresh
    before_empty = _mean(lab_distance(before, empty_crop), mc) < cfg.empty_thresh
    if after_empty and before_empty:
        return None
    if after_empty:
        return "removed"
    if before_empty:
        return "added"
    # Something on something: if what's visible now looks like an item we remembered under this spot,
    # and clearly MORE like it than what was there before, the top one left. Relative, so features
    # that find everything similar (pooled CNN embeddings on look-alike packs) can't fake a reveal.
    fp_after, fp_before = features(blob.after_core), features(blob.before_core)
    for _, view in cart.views_in(blob.cam):
        if _iou(view.box, blob.box) <= IOU_OVERLAP:
            continue
        s_after, s_before = _sim(fp_after, view.fingerprint), _sim(fp_before, view.fingerprint)
        if s_after >= cfg.local_min_score and s_after - s_before >= cfg.local_min_margin:
            return "removed"
    return "added"


def _views(blobs: list[Blob], features) -> dict[int, View]:
    return {b.cam: View(b.cam, b.box, features(b.after_core).tolist()) for b in blobs}


def _decide_added(added: dict[int, list[Blob]], identifier, features) -> list[Decision]:
    if not added:
        return []
    n = max(len(bs) for bs in added.values())
    if n == 1:  # the common case: both cameras saw the same single item
        # biggest view first: if one camera's blob is spurious (a shadow), the good view leads (Claude gets ≤ 2)
        blobs = sorted((bs[0] for bs in added.values()), key=lambda b: -b.area_frac)
        ident = identifier.identify([b.after_core for b in blobs], cloud_crops=[b.after for b in blobs])
        return [Decision("added", ident.product_id, ident.confidence, ident.method, ident.label,
                         sorted(b.cam for b in blobs), blobs, _views(blobs, features), count=max(1, ident.count))]

    idents = {id(b): identifier.identify([b.after_core], cloud_crops=[b.after]) for bs in added.values() for b in bs}
    by_pid: dict[str, dict[int, list[Blob]]] = {}
    for cam, bs in added.items():
        for b in bs:
            pid = idents[id(b)].product_id
            if pid is not None:
                by_pid.setdefault(pid, {}).setdefault(cam, []).append(b)

    candidates = []  # (confidence, pid, blobs for one unit)
    for pid, per_cam in by_pid.items():
        for cam in per_cam:
            per_cam[cam].sort(key=lambda b: -idents[id(b)].confidence)
        for i in range(max(len(v) for v in per_cam.values())):
            unit = [v[i] for v in per_cam.values() if len(v) > i]
            candidates.append((max(idents[id(b)].confidence for b in unit), pid, unit))
    candidates.sort(key=lambda c: -c[0])

    decisions, used = [], set()
    for conf, pid, unit in candidates[:n]:
        first = idents[id(unit[0])]
        decisions.append(Decision("added", pid, conf, first.method, first.label,
                                  sorted(b.cam for b in unit), unit, _views(unit, features), count=max(1, first.count)))
        used.update(id(b) for b in unit)

    busiest = max(added, key=lambda c: len(added[c]))
    for b in [b for b in added[busiest] if id(b) not in used][: n - len(decisions)]:
        ident = idents[id(b)]
        decisions.append(Decision("added", None, ident.confidence, "none", ident.label, [b.cam], [b],
                                  _views([b], features)))
    return decisions


def _coverage(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> float:
    """Fraction of box `inner` that lies inside box `outer`."""
    ix = max(0, min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0]))
    iy = max(0, min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1]))
    area = inner[2] * inner[3]
    return ix * iy / area if area > 0 else 0.0


def _decide_removed(removed: dict[int, list[Blob]], cart: CartMemory, features, cfg) -> list[Decision]:
    """Match removal blobs to remembered units, by place first.

    A unit this camera remembers only qualifies if it overlaps the emptied spot; a unit it never saw
    qualifies only on a strong look-alike match. Every unit whose spot emptied counts, so an item and
    an unknown remembered at the same spot both go. Nothing qualifies → nothing is removed (taking out
    something that was never billed must not remove something else).
    """
    if not removed or not cart.instances:
        return []
    fps = {id(b): features(b.before_core) for bs in removed.values() for b in bs}
    totals: dict[str, float] = {}
    best_sim: dict[str, float] = {}
    best_blobs: dict[str, dict[int, Blob]] = {}
    wanted = 0
    for cam, bs in removed.items():
        vanished = 0
        for inst in cart.instances.values():
            best = None
            for b in bs:
                if cam in inst.views:
                    v = inst.views[cam]
                    iou = _iou(b.box, v.box)
                    if iou <= 0.0:
                        continue
                    sim = _sim(fps[id(b)], v.fingerprint)
                    score = sim + IOU_WEIGHT * iou
                else:
                    sim = max((_sim(fps[id(b)], v.fingerprint) for v in inst.views.values()), default=0.0)
                    if sim < cfg.local_min_score:
                        continue
                    score = sim
                if best is None or score > best[0]:
                    best = (score, sim, b)
            if cam in inst.views and any(_coverage(inst.views[cam].box, b.box) >= VANISHED_COVERAGE for b in bs):
                vanished += 1
            if best is not None:
                iid = inst.instance_id
                totals[iid] = totals.get(iid, 0.0) + best[0]
                best_sim[iid] = max(best_sim.get(iid, 0.0), best[1])
                best_blobs.setdefault(iid, {})[cam] = best[2]
        wanted = max(wanted, len(bs), vanished)
    chosen = sorted(totals, key=lambda iid: -totals[iid])[:min(wanted, len(totals))]
    out = []
    for iid in chosen:
        inst: Instance = cart.instances[iid]
        blobs = best_blobs[iid]
        out.append(Decision("removed", inst.product_id, min(1.0, max(0.0, best_sim[iid])), "memory", inst.label,
                            sorted(blobs), list(blobs.values()), {}, iid))
    return out


def _same_item(add: Decision, rem: Decision, cart: CartMemory, cfg) -> bool:
    if add.product_id is not None:
        return add.product_id == rem.product_id
    # An unknown add that looks just like the item that left (same camera) is that item, moved.
    inst = cart.instances.get(rem.instance_id)
    if inst is None:
        return False
    return any(cam in inst.views and _sim(v.fingerprint, inst.views[cam].fingerprint) >= cfg.local_min_score
               for cam, v in add.views.items())


def _cancel_nudges(decisions: list[Decision], cart: CartMemory, cfg) -> list[Decision]:
    adds = [d for d in decisions if d.kind == "added"]
    out = []
    for rem in (d for d in decisions if d.kind == "removed"):
        match = next((a for a in adds if _same_item(a, rem, cart, cfg)), None)
        if match is None:
            out.append(rem)
            continue
        adds.remove(match)
        out.append(Decision("moved", rem.product_id, match.confidence, match.method, rem.label,
                            match.cameras, match.blobs, match.views, rem.instance_id))
    return adds + out


def decide(results: list[ChangeResult], empties: dict[int, np.ndarray], cart: CartMemory,
           identifier, features, cfg) -> list[Decision]:
    added: dict[int, list[Blob]] = {}
    removed: dict[int, list[Blob]] = {}
    for r in results:
        if r.status != "blobs":
            continue
        empty = empties.get(r.cam)
        if empty is None:
            # Without an empty-basket picture a removal looks like an addition; let the other camera decide.
            log.warning("cam%d has no empty-basket picture yet; ignoring its changes (reset with the cart empty)", r.cam)
            continue
        matched = gain_matched(r, empty, cfg.roi.get(str(r.cam)), cart)
        for b in r.blobs:
            kind = classify_blob(b, r, empty, cart, features, cfg, matched)
            if kind == "added":
                added.setdefault(r.cam, []).append(b)
            elif kind == "removed":
                removed.setdefault(r.cam, []).append(b)
    # A camera held back when an item was billed (an arm in its view) now sees that spot: the same unit,
    # seen late. Attach the view instead of billing it twice.
    late = []
    for cam, bs in list(added.items()):
        for inst in list(cart.instances.values()):
            spots = inst.awaiting.get(cam) or []
            b = next((b for b in bs if any(_coverage(b.box, s) >= 0.5 or _iou(b.box, s) >= 0.2 for s in spots)), None)
            if b is not None:
                bs.remove(b)
                late.append(Decision("moved", inst.product_id, 1.0, "memory", inst.label, [cam], [b],
                                     _views([b], features), inst.instance_id))
        if not bs:
            del added[cam]
    # cameras that had a clean look this settle: earlier held-back spots in them have had their chance
    cart.expire_awaiting({r.cam for r in results if r.status in ("blobs", "none") and not r.deferred})

    decisions = _decide_added(added, identifier, features) + _decide_removed(removed, cart, features, cfg)
    held = {r.cam: list(r.deferred) for r in results if r.deferred}
    for d in decisions:
        if d.kind == "added":
            d.awaiting = {c: boxes for c, boxes in held.items() if c not in d.cameras}
    return late + _cancel_nudges(decisions, cart, cfg)


def apply_decision(cart: CartMemory, d: Decision) -> Instance | None:
    if d.kind == "added":
        return cart.add(d.product_id, d.label, d.views, d.awaiting)
    if d.kind == "removed":
        return cart.remove(d.instance_id) if d.instance_id in cart.instances else None
    if d.kind == "moved":
        cart.update_views(d.instance_id, d.views)
        return cart.instances[d.instance_id]
    return None
