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

log = logging.getLogger(__name__)

IOU_OVERLAP = 0.1
IOU_WEIGHT = 0.2


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


def classify_blob(blob: Blob, result: ChangeResult, empty: np.ndarray, cart: CartMemory, features, cfg) -> str | None:
    empty_crop = _crop(empty, blob.box)
    after = _crop(match_gain(result.frame, empty), blob.box)
    before = _crop(match_gain(result.reference, empty), blob.box)
    after_empty = float(lab_distance(after, empty_crop).mean()) < cfg.empty_thresh
    before_empty = float(lab_distance(before, empty_crop).mean()) < cfg.empty_thresh
    if after_empty and before_empty:
        return None
    if after_empty:
        return "removed"
    if before_empty:
        return "added"
    # Something on something: if what's visible now is an item we remembered under this spot, the top one left.
    fp_after = features(blob.after_core)
    for _, view in cart.views_in(blob.cam):
        if _iou(view.box, blob.box) > IOU_OVERLAP and _sim(fp_after, view.fingerprint) >= cfg.local_min_score:
            return "removed"
    return "added"


def _views(blobs: list[Blob], features) -> dict[int, View]:
    return {b.cam: View(b.cam, b.box, features(b.after_core).tolist()) for b in blobs}


def _decide_added(added: dict[int, list[Blob]], identifier, features) -> list[Decision]:
    if not added:
        return []
    n = max(len(bs) for bs in added.values())
    if n == 1:  # the common case: both cameras saw the same single item
        blobs = [bs[0] for bs in added.values()]
        ident = identifier.identify([b.after_core for b in blobs], cloud_crops=[b.after for b in blobs])
        return [Decision("added", ident.product_id, ident.confidence, ident.method, ident.label,
                         sorted(b.cam for b in blobs), blobs, _views(blobs, features))]

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
                                  sorted(b.cam for b in unit), unit, _views(unit, features)))
        used.update(id(b) for b in unit)

    busiest = max(added, key=lambda c: len(added[c]))
    for b in [b for b in added[busiest] if id(b) not in used][: n - len(decisions)]:
        ident = idents[id(b)]
        decisions.append(Decision("added", None, ident.confidence, "none", ident.label, [b.cam], [b],
                                  _views([b], features)))
    return decisions


def _decide_removed(removed: dict[int, list[Blob]], cart: CartMemory, features) -> list[Decision]:
    if not removed or not cart.instances:
        return []
    n = min(max(len(bs) for bs in removed.values()), len(cart.instances))
    fps = {id(b): features(b.before_core) for bs in removed.values() for b in bs}
    totals: dict[str, float] = {}
    best_sim: dict[str, float] = {}
    best_blobs: dict[str, dict[int, Blob]] = {}
    for cam, bs in removed.items():
        for inst in cart.instances.values():
            best = None
            for b in bs:
                if cam in inst.views:
                    v = inst.views[cam]
                    sim = _sim(fps[id(b)], v.fingerprint)
                    score = sim + IOU_WEIGHT * _iou(b.box, v.box)
                else:
                    sim = max((_sim(fps[id(b)], v.fingerprint) for v in inst.views.values()), default=0.0)
                    score = sim
                if best is None or score > best[0]:
                    best = (score, sim, b)
            if best is not None:
                iid = inst.instance_id
                totals[iid] = totals.get(iid, 0.0) + best[0]
                best_sim[iid] = max(best_sim.get(iid, 0.0), best[1])
                best_blobs.setdefault(iid, {})[cam] = best[2]
    chosen = sorted(totals, key=lambda iid: -totals[iid])[:n]
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
        for b in r.blobs:
            kind = classify_blob(b, r, empty, cart, features, cfg)
            if kind == "added":
                added.setdefault(r.cam, []).append(b)
            elif kind == "removed":
                removed.setdefault(r.cam, []).append(b)
    decisions = _decide_added(added, identifier, features) + _decide_removed(removed, cart, features)
    return _cancel_nudges(decisions, cart, cfg)


def apply_decision(cart: CartMemory, d: Decision) -> Instance | None:
    if d.kind == "added":
        return cart.add(d.product_id, d.label, d.views)
    if d.kind == "removed":
        return cart.remove(d.instance_id) if d.instance_id in cart.instances else None
    if d.kind == "moved":
        cart.update_views(d.instance_id, d.views)
        return cart.instances[d.instance_id]
    return None
