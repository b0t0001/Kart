"""Turn per-camera change blobs into cart decisions (spec §5.3, §5.4, §6.2).

Each blob is classified added/removed against the empty-basket picture and cart memory. The two
cameras are then combined into one decision per physical unit: a product's count changes by the most
units any single camera saw. Added units are identified (gallery, then Claude); removed units are
matched only against what the cart remembers. Same-product add+remove in one settle is a move.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import logging

import cv2
import numpy as np

from kartcv.cart import CartMemory, Instance, View
from kartcv.changes import Blob, ChangeResult, lab_distance, match_gain
from kartcv.roi import gray_outside, polygon_mask

log = logging.getLogger(__name__)

IOU_OVERLAP = 0.1
IOU_WEIGHT = 0.2
VANISHED_COVERAGE = 0.6  # a remembered unit whose box is this much inside an emptied spot is gone
SAME_SPOT_IOU = 0.5      # a change this much on a remembered unit's box, still looking like it, is that unit
GROWTH = 1.5             # ...unless this much more of the spot is covered now: something else was put down
GONE_MIN = 0.4           # a remembered unit can only be taken off if this much of its own footprint changed
LOOK_WEIGHT = 0.2        # where comes first; look only ranks units whose footprints emptied alike
LINER_MAX = 0.85         # a spot whose pixels are this much the liner's own colors is bare liner
LINER_TOL = np.float32([60, 6, 6])  # LAB: a crease changes the liner's lightness, hardly its color
NEAR = 0.05              # of the frame width: pieces of one item this close in a camera are at one spot
FAINT_GONE = 0.6         # a remembered spot this emptied with no blob over it (only a sliver ever showed)...
FAINT_BARE = 0.85        # ...whose changed part is now this much bare floor: that unit was taken out


@dataclass
class Decision:
    kind: str  # "added" | "removed" | "moved" | "held" (a lone unknown waiting for the recheck)
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
    personal: bool = False  # the shopper's own belonging: memory only, no event
    private: bool = False   # came in from the frame edge: its photos never leave the cart (edge_privacy)
    placement: str = ""     # added: the hand-in that brought it
    asked: bool = False     # added unknown: Claude looked and couldn't name it (not a timeout)


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


def _lab(img: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
    return lab[mask.reshape(-1).astype(bool)] if mask is not None else lab


def liner_model(empty: np.ndarray, mask: np.ndarray | None) -> tuple[np.ndarray, np.ndarray]:
    """The bare liner's colors from the empty picture's floor: typical LAB color (median, so an item left
    in the picture doesn't count) and how far from it the liner itself goes (its spread, or LINER_TOL)."""
    ref = _lab(empty[::4, ::4], mask[::4, ::4] if mask is not None else None)
    med = np.median(ref, axis=0)
    return med, np.maximum(3 * 1.4826 * np.median(np.abs(ref - med), axis=0), LINER_TOL)


def liner_share(crop: np.ndarray, crop_mask: np.ndarray | None, model: tuple) -> float:
    """Share of the crop's pixels (inside crop_mask, if any) in the bare liner's own colors."""
    med, tol = model
    px = _lab(crop, crop_mask)
    return float((np.abs(px - med) <= tol).all(axis=1).mean()) if len(px) else 1.0


def _bare_liner(img: np.ndarray, box: tuple[int, int, int, int], m: np.ndarray | None, model) -> bool:
    x, y, w, h = box
    return liner_share(img[y:y + h, x:x + w], m[y:y + h, x:x + w] if m is not None else None, model) >= LINER_MAX


def _foreground(img: np.ndarray, empty: np.ndarray, box: tuple[int, int, int, int], m: np.ndarray | None,
                cfg) -> np.ndarray:
    """The part of a box that isn't bare floor: cropped to the pixels that differ from the empty picture,
    so a sliver of a remembered item revealed in a mostly-empty spot is fingerprinted as that item."""
    x, y, w, h = box
    d = lab_distance(img[y:y + h, x:x + w], empty[y:y + h, x:x + w]) > cfg.change_thresh
    if m is not None:
        d &= m[y:y + h, x:x + w].astype(bool)
    ys, xs = np.nonzero(d)
    if len(ys) < 0.05 * max(1, d.size):
        return img[y:y + h, x:x + w]
    return img[y + ys.min():y + ys.max() + 1, x + xs.min():x + xs.max() + 1]


def _covered(crop: np.ndarray, empty_crop: np.ndarray, m: np.ndarray | None, cfg) -> float:
    """Share of the floor in this crop that something lies on (differs from the empty basket)."""
    return _mean((lab_distance(crop, empty_crop) > cfg.change_thresh).astype(np.float32), m)


def settled_unit(blob: Blob, cart: CartMemory, fp_after, cfg) -> Instance | None:
    """The remembered unit this change sits on and still looks like, if any (best overlap first)."""
    best = None
    for inst, view in cart.views_in(blob.cam):
        iou = _iou(view.box, blob.box)
        if iou >= SAME_SPOT_IOU and _sim(fp_after, view.fingerprint) >= cfg.local_min_score:
            if best is None or iou > best[0]:
                best = (iou, inst)
    return best[1] if best else None


def classify_blob(blob: Blob, result: ChangeResult, empty: np.ndarray, cart: CartMemory, features, cfg,
                  matched: tuple | None = None, liner: tuple | None = None) -> str | None:
    """One of "added", "removed", "settled" (a remembered unit changed shape or shifted in its spot), or None."""
    cur, ref, m = matched if matched is not None else gain_matched(result, empty, cfg.roi.get(str(blob.cam)), cart)
    liner = liner if liner is not None else liner_model(empty, m)
    empty_crop = _crop(empty, blob.box)
    after = _crop(cur, blob.box)
    before = _crop(ref, blob.box)
    mc = _crop(m, blob.box) if m is not None else None  # judge the floor only, not the room behind it
    # Empty = hardly any of the changed box itself differs from the empty picture (a share, not a mean
    # distance: a dark box lying diagonally on a dark liner fills a third of its box, and a mean over it
    # nearly passed for empty), or bare liner: its creases shift, and something lying there when the
    # empty picture was taken leaves bare liner behind when it's lifted.
    core = blob.core_box
    e_core, m_core = _crop(empty, core), (_crop(m, core) if m is not None else None)
    after_empty = (_covered(_crop(cur, core), e_core, m_core, cfg) < cfg.empty_share
                   or _bare_liner(cur, core, m, liner))
    before_empty = (_covered(_crop(ref, core), e_core, m_core, cfg) < cfg.empty_share
                    or _bare_liner(ref, core, m, liner))
    if after_empty and before_empty:
        return None
    if after_empty:
        return "removed"
    if before_empty:
        return "added"
    # Something on something. If clearly more of the spot is covered now, something was put down (a
    # second box set against the first, nudging it): an add, never a reveal.
    if _covered(after, empty_crop, mc, cfg) >= GROWTH * max(_covered(before, empty_crop, mc, cfg), 0.05):
        return "added"
    # If what's visible now looks like an item we remembered under this spot, and clearly MORE like it
    # than what was there before, the top one left. Relative, so features that find everything
    # similar (pooled CNN embeddings on look-alike packs) can't fake a reveal.
    fp_after = features(_foreground(cur, empty, core, m, cfg))
    fp_before = features(_foreground(ref, empty, core, m, cfg))
    for _, view in cart.views_in(blob.cam):
        if _iou(view.box, blob.box) <= IOU_OVERLAP:
            continue
        s_after, s_before = _sim(fp_after, view.fingerprint), _sim(fp_before, view.fingerprint)
        if s_after >= cfg.local_min_score and s_after - s_before >= cfg.local_min_margin:
            return "removed"
    # A remembered unit that changed in its own spot, covering about as much as before: a soft bag
    # slumping, a box nudged. Same unit: memory follows it, nothing is billed. Laying a different item
    # over it fails the look-alike test; a smaller one stacked on top fails the overlap test.
    if settled_unit(blob, cart, fp_after, cfg) is not None:
        return "settled"
    return "added"


def _views(blobs: list[Blob], features) -> dict[int, View]:
    return {b.cam: View(b.cam, b.box, features(b.after_core).tolist()) for b in blobs}


def _merged_view(blobs: list[Blob], features) -> View:
    """One camera's view of one unit seen as several blobs: their joint box, the biggest one's look."""
    x0, y0 = min(b.box[0] for b in blobs), min(b.box[1] for b in blobs)
    x1, y1 = max(b.box[0] + b.box[2] for b in blobs), max(b.box[1] + b.box[3] for b in blobs)
    big = max(blobs, key=lambda b: b.area_frac)
    return View(big.cam, (x0, y0, x1 - x0, y1 - y0), features(big.after_core).tolist())


def _decide_added(added: dict[int, list[Blob]], identifier, features, cfg) -> list[Decision]:
    if not added:
        return []
    n = max(len(bs) for bs in added.values())
    if n == 1:  # the common case: both cameras saw the same single item
        # biggest view first: if one camera's blob is spurious (a shadow), the good view leads (Claude gets ≤ 2)
        blobs = sorted((bs[0] for bs in added.values()), key=lambda b: -b.area_frac)
        private = cfg.edge_privacy and any(b.edge for b in blobs)
        ident = identifier.identify([b.after_core for b in blobs], cloud_crops=[b.ident_crop for b in blobs],
                                    allow_cloud=not private)
        return [Decision("added", ident.product_id, ident.confidence, ident.method, ident.label,
                         sorted(b.cam for b in blobs), blobs, _views(blobs, features), count=max(1, ident.count),
                         personal=ident.personal, private=private, asked=getattr(ident, "asked", False))]

    idents = {id(b): identifier.identify([b.after_core], cloud_crops=[b.ident_crop],
                                         allow_cloud=not (cfg.edge_privacy and b.edge))
              for bs in added.values() for b in bs}
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
                                  sorted(b.cam for b in unit), unit, _views(unit, features), count=max(1, first.count),
                                  private=cfg.edge_privacy and any(b.edge for b in unit)))
        used.update(id(b) for b in unit)

    busiest = max(added, key=lambda c: len(added[c]))
    for b in [b for b in added[busiest] if id(b) not in used][: n - len(decisions)]:
        ident = idents[id(b)]
        decisions.append(Decision("added", None, ident.confidence, ident.method, ident.label, [b.cam], [b],
                                  _views([b], features), personal=ident.personal, private=cfg.edge_privacy and b.edge,
                                  asked=getattr(ident, "asked", False)))
    return decisions


def _coverage(inner: tuple[int, int, int, int], outer: tuple[int, int, int, int]) -> float:
    """Fraction of box `inner` that lies inside box `outer`."""
    ix = max(0, min(inner[0] + inner[2], outer[0] + outer[2]) - max(inner[0], outer[0]))
    iy = max(0, min(inner[1] + inner[3], outer[1] + outer[3]) - max(inner[1], outer[1]))
    area = inner[2] * inner[3]
    return ix * iy / area if area > 0 else 0.0


def _spot(box: tuple[int, int, int, int], matched: tuple, empty: np.ndarray | None, cfg,
          liner: tuple | None = None) -> tuple[float, float]:
    """(gone, bare) for a remembered unit's box. gone: how much of what lay there (whatever differed from
    the empty basket) changed this settle, so a thin arm in a tall box scores high when it leaves and a
    box still lying there scores low, however much a neighbour's emptied spot overlaps it. bare: how
    much of that changed part is bare floor now (the empty picture, or the liner's own colors)."""
    cur, ref, m = matched
    x, y, w, h = box
    a, b = cur[y:y + h, x:x + w], ref[y:y + h, x:x + w]
    if a.size == 0:
        return 0.0, 0.0
    a_s, b_s = cv2.GaussianBlur(a, (7, 7), 0), cv2.GaussianBlur(b, (7, 7), 0)
    changed = lab_distance(a_s, b_s) > cfg.change_thresh
    floor = m[y:y + h, x:x + w].astype(bool) if m is not None else np.ones(changed.shape, bool)
    there, bare = floor, 0.0
    if empty is not None:
        e_s = cv2.GaussianBlur(empty[y:y + h, x:x + w], (7, 7), 0)
        occupied = floor & (lab_distance(b_s, e_s) > cfg.change_thresh)
        if occupied.sum() >= 0.02 * max(1, floor.sum()):
            there = occupied
        gone_px = changed & there
        if liner is not None and gone_px.any():
            med, tol = liner
            like_liner = (np.abs(cv2.cvtColor(a, cv2.COLOR_BGR2LAB).astype(np.float32) - med) <= tol).all(axis=2)
            like_empty = lab_distance(a_s, e_s) < cfg.change_thresh
            bare = float((like_liner | like_empty)[gone_px].mean())
    return float((changed & there).sum()) / max(1, int(there.sum())), bare


def _emptied(box: tuple[int, int, int, int], matched: tuple, empty: np.ndarray | None, cfg) -> float:
    return _spot(box, matched, empty, cfg)[0]


def _faint_removals(results: list[ChangeResult], empties: dict, cart: CartMemory, cfg, matched: dict,
                    decided: set) -> list[Decision]:
    """Units taken out with no blob over their spot: only a sliver of them ever showed (a card lying
    behind a jar), too small to make a blob. Every clean camera that remembers the unit must see its
    spot emptied to bare floor, and no blob or held-back change in that camera may touch it."""
    votes: dict[str, list] = {}
    blocked: set[str] = set()
    for r in results:
        empty = empties.get(r.cam)
        if empty is None or r.moved or r.status not in ("none", "blobs") or r.frame is None:
            continue  # this camera can't judge: no vote
        views = [(i, v) for i, v in cart.views_in(r.cam) if i.instance_id not in decided]
        if not views:
            continue
        mt = matched.get(r.cam) or gain_matched(r, empty, cfg.roi.get(str(r.cam)), cart)
        liner = liner_model(empty, mt[2])
        for inst, v in views:
            if r.deferred or any(_iou(b.box, v.box) > 0 for b in r.blobs):
                blocked.add(inst.instance_id)
                continue
            gone, bare = _spot(v.box, mt, empty, cfg, liner)
            votes.setdefault(inst.instance_id, []).append((gone >= FAINT_GONE and bare >= FAINT_BARE, r, v, mt))
    out = []
    for iid, vs in votes.items():
        if iid in blocked or not all(ok for ok, *_ in vs):
            continue
        inst = cart.instances[iid]
        blobs = []
        for _, r, v, mt in vs:
            x, y, w, h = v.box
            mc = mt[2][y:y + h, x:x + w] if mt[2] is not None else None
            blobs.append(Blob(r.cam, v.box, 0.0, gray_outside(r.reference[y:y + h, x:x + w], mc),
                              gray_outside(r.frame[y:y + h, x:x + w], mc)))
            log.info("TAKEN OUT: cam%d sees %s's spot emptied (too small a change for a blob)", r.cam, inst.label)
        out.append(Decision("removed", inst.product_id, 1.0, "memory", inst.label, sorted(b.cam for b in blobs),
                            blobs, {}, iid, personal=inst.personal))
    return out


def _decide_removed(removed: dict[int, list[Blob]], cart: CartMemory, features, cfg,
                    matched: dict[int, tuple] | None = None, empties: dict | None = None) -> list[Decision]:
    """Match removal blobs to remembered units, by place first.

    A unit this camera remembers only qualifies if the emptied spot overlaps it AND its own footprint
    changed (GONE_MIN): one still sitting there is never taken off, however its neighbour's spot
    overlaps it. Among those, the most-emptied footprint wins; look only ranks near-ties. A unit this
    camera never saw qualifies only on a strong look-alike match, ranked below any place match. Every
    unit whose footprint emptied counts, so an item and an unknown remembered at the same spot both
    go. Nothing qualifies → nothing is removed (taking out something that was never billed must not
    remove something else).
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
            if cam in inst.views:
                v = inst.views[cam]
                hit = [b for b in bs if _iou(b.box, v.box) > 0.0]
                if not hit:
                    continue
                gone = (_emptied(v.box, matched[cam], (empties or {}).get(cam), cfg) if matched and cam in matched
                        else max(_coverage(v.box, b.box) for b in hit))
                if gone < GONE_MIN:
                    continue
                vanished += gone >= VANISHED_COVERAGE
                b = max(hit, key=lambda b: _sim(fps[id(b)], v.fingerprint))
                sim = _sim(fps[id(b)], v.fingerprint)
                best = (gone + LOOK_WEIGHT * sim, sim, b)
            else:
                for b in bs:
                    sim = max((_sim(fps[id(b)], v.fingerprint) for v in inst.views.values()), default=0.0)
                    if sim >= cfg.local_min_score and (best is None or sim > best[1]):
                        best = (LOOK_WEIGHT * sim, sim, b)
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
                            sorted(blobs), list(blobs.values()), {}, iid, personal=inst.personal))
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
    out = [d for d in decisions if d.kind not in ("added", "removed")]
    for rem in (d for d in decisions if d.kind == "removed"):
        match = next((a for a in adds if _same_item(a, rem, cart, cfg)), None)
        if match is None:
            out.append(rem)
            continue
        adds.remove(match)
        out.append(Decision("moved", rem.product_id, match.confidence, match.method, rem.label,
                            match.cameras, match.blobs, match.views, rem.instance_id, placement=match.placement))
    return adds + out


def _near(a: tuple[int, int, int, int], b: tuple[int, int, int, int], margin: float) -> bool:
    return (a[0] - margin < b[0] + b[2] and b[0] - margin < a[0] + a[2]
            and a[1] - margin < b[1] + b[3] and b[1] - margin < a[1] + a[3])


def _join_view(old: View, new: View) -> View:
    x0, y0 = min(old.box[0], new.box[0]), min(old.box[1], new.box[1])
    x1 = max(old.box[0] + old.box[2], new.box[0] + new.box[2])
    y1 = max(old.box[1] + old.box[3], new.box[1] + new.box[3])
    return View(old.cam, (x0, y0, x1 - x0, y1 - y0), old.fingerprint, old.crop_path)


def _one_per_placement(decisions: list[Decision], cart: CartMemory, placement: str | None,
                       widths: dict[int, int]) -> list[Decision]:
    """One placement (one hand in and out) brings one unit of a product. Another "added" in the same
    placement is more of that unit, not a second one, when it is:
      - the same product (or unknown): a piece next to it in this settle (a box its own print cuts in
        two), a view from a camera that hadn't seen it (a camera that looks only now), or a view
        lying mostly on its box;
      - any product, seen by ONE camera only: a piece right next to it in this settle that the other
        camera explains as part of it, or a camera's first view of it (cam0's close-up of a jar's lid,
        which the gallery may even misname, while cam1 names the jar).
    The better-explained add (more cameras) goes first, so the lone piece joins it, not the reverse.
    An unknown billed first is replaced once the other camera names it. Anything at a distinct spot in
    a camera that sees both is a second unit: two items put in together, apart, are two, and a box set
    beside one billed earlier is billed even if its hand-in went unseen."""
    if placement is None:
        return decisions
    leaving = {d.instance_id for d in decisions if d.kind == "removed"}
    billed = [i for i in cart.instances.values() if i.instance_id not in leaving]
    new: list[Decision] = []
    out = [d for d in decisions if d.kind != "added"]
    for d in sorted((d for d in decisions if d.kind == "added"), key=lambda d: -len(set(d.cameras))):
        lone = len(set(d.cameras)) == 1
        # a change that waited on an intrusion belongs to the hand-in it started in, not today's
        place = next((b.placement for b in d.blobs if b.placement), placement)
        twin = None
        for u in reversed([i for i in billed if i.placement == place] + [n for n in new if n.placement == place]):
            same_product = d.product_id is None or u.product_id is None or u.product_id == d.product_id
            shared = [b for b in d.blobs if b.cam in u.views]
            if isinstance(u, Decision):  # pieces seen in this same settle: next to each other is enough
                near = any(_near(b.box, u.views[b.cam].box, NEAR * widths.get(b.cam, 1280)) for b in shared)
                explained = bool(set(u.views) - set(d.cameras))  # another camera saw it but not this piece
                ok = (same_product and (not shared or near)) or (lone and near and explained)
            else:  # a unit billed earlier in this hand-in: a camera's first view of it, one lying on it, or a
                late = not shared  # lone view that waited on an intrusion, right next to the piece already seen
                on_it = any(_coverage(b.box, u.views[b.cam].box) >= 0.5 for b in shared)  # (jar body, its lid)
                near = any(_near(b.box, u.views[b.cam].box, NEAR * widths.get(b.cam, 1280)) for b in shared)
                waited = any(b.placement for b in d.blobs)
                ok = (same_product and (late or on_it or (lone and near and waited))) or (lone and late)
            if ok:
                twin = u
                break
        if twin is None and lone and d.product_id is not None:
            # A named view from ONE camera, of a product billed in an earlier hand-in while this very camera
            # was held back (an arm at the edge) and still has no view of it: that item, seen late, never a
            # second one, even if its held-back spot doesn't line up. Only then: identical boxes each seen
            # by one camera (cam0's blind zone) stay separate units.
            cam = d.cameras[0]
            for u in sorted(billed, key=lambda i: i.added_ts, reverse=True):
                if u.product_id == d.product_id and cam not in u.views and u.awaiting.get(cam):
                    twin = u
                    break
        if twin is None:
            d.placement = place
            out.append(d)
            new.append(d)
            continue
        views = {c: _join_view(twin.views[c], v) if c in twin.views else v for c, v in d.views.items()}
        if isinstance(twin, Decision):  # an add earlier in this settle: fold this one into it
            log.info("ONE UNIT: cam%s's %s is part of %s", ",".join(map(str, d.cameras)), d.label, twin.label)
            twin.blobs += d.blobs
            twin.cameras = sorted(set(twin.cameras) | set(d.cameras))
            twin.views.update(views)
        elif twin.product_id is None and d.product_id is not None:  # the other camera names the unknown
            log.info("NAMED: the unknown billed from cam%s is %s: replaced", ",".join(map(str, twin.views)),
                     d.label)
            merged = {**twin.views, **views}
            out.append(Decision("removed", None, 1.0, "memory", twin.label, sorted(twin.views), [], {},
                                twin.instance_id, personal=twin.personal))
            out.append(Decision("added", d.product_id, d.confidence, d.method, d.label, sorted(merged), d.blobs,
                                merged, count=d.count, private=d.private, placement=place))
        else:
            log.info("ONE UNIT: %s again in the same placement: more of the same unit, not a second one", d.label)
            out.append(Decision("moved", twin.product_id, d.confidence, d.method, twin.label, d.cameras, d.blobs,
                                views, twin.instance_id))
    return out


def decide(results: list[ChangeResult], empties: dict[int, np.ndarray], cart: CartMemory,
           identifier, features, cfg, placement: str | None = None, placement_used: bool = False) -> list[Decision]:
    added: dict[int, list[Blob]] = {}
    removed: dict[int, list[Blob]] = {}
    settled: list[Decision] = []
    matched_by_cam: dict[int, tuple] = {}
    for r in results:
        if r.status != "blobs":
            continue
        empty = empties.get(r.cam)
        if empty is None:
            # Without an empty-basket picture a removal looks like an addition; let the other camera decide.
            log.warning("cam%d has no empty-basket picture yet; ignoring its changes (reset with the cart empty)", r.cam)
            continue
        matched = matched_by_cam[r.cam] = gain_matched(r, empty, cfg.roi.get(str(r.cam)), cart)
        liner = liner_model(empty, matched[2])
        for b in r.blobs:
            kind = classify_blob(b, r, empty, cart, features, cfg, matched, liner)
            if kind == "added":
                added.setdefault(r.cam, []).append(b)
            elif kind == "removed":
                removed.setdefault(r.cam, []).append(b)
            elif kind == "settled":
                inst = settled_unit(b, cart, features(b.after_core), cfg)
                log.info("SETTLED IN PLACE: cam%d sees %s shift or change shape in its spot: updated, not billed",
                         r.cam, inst.label)
                settled.append(Decision("moved", inst.product_id, 1.0, "memory", inst.label, [r.cam], [b],
                                        _views([b], features), inst.instance_id))
    # A camera held back when an item was billed (an arm in its view) now sees that spot: the same unit,
    # seen late. Attach the view instead of billing it twice: all of it, even split into several blobs
    # (a flat box along the frame edge, cut in two by its own print).
    late = []
    for cam, bs in list(added.items()):
        for inst in list(cart.instances.values()):
            spots = inst.awaiting.get(cam) or []
            hits = [b for b in bs if any(_coverage(b.box, s) >= 0.5 or _iou(b.box, s) >= 0.2 for s in spots)]
            if hits:
                for b in hits:
                    bs.remove(b)
                late.append(Decision("moved", inst.product_id, 1.0, "memory", inst.label, [cam], hits,
                                     {cam: _merged_view(hits, features)}, inst.instance_id))
        if not bs:
            del added[cam]
    # cameras that had a clean look this settle: earlier held-back spots in them have had their chance
    cart.expire_awaiting({r.cam for r in results if r.status in ("blobs", "none") and not r.deferred})

    decisions = (_decide_added(added, identifier, features, cfg)
                 + _decide_removed(removed, cart, features, cfg, matched_by_cam, empties))
    held = {r.cam: list(r.deferred) for r in results if r.deferred}
    for d in decisions:
        if d.kind == "added":
            d.awaiting = {c: boxes for c, boxes in held.items() if c not in d.cameras}
    widths = {r.cam: r.frame.shape[1] for r in results if r.frame is not None}
    decisions = _one_per_placement(decisions, cart, placement, widths)
    decided = {d.instance_id for d in late + settled + decisions if d.instance_id}
    faint = _faint_removals(results, empties, cart, cfg, matched_by_cam, decided)
    out = late + settled + _cancel_nudges(decisions, cart, cfg) + faint
    # A lone unknown that Claude looked at and couldn't name, while every other camera had a clean look
    # and saw nothing new: one camera's glimpse (a liner corner by the grate, a lid close-up), never billed.
    # Not when Claude failed (a timeout is no verdict), nor offline: those still bill as unknown.
    def corroborated(d: Decision) -> bool:
        others = [r for r in results if r.cam not in d.cameras]
        if not others:
            return True
        for r in others:
            if r.moved or r.deferred or r.status not in ("none", "blobs") or r.cam not in empties:
                return True  # that camera couldn't look
            if any(r.cam in o.cameras and o.kind in ("added", "moved") for o in out if o is not d):
                return True  # it saw something new too
        return False
    for d in [d for d in out if d.kind == "added" and d.product_id is None and d.asked and len(set(d.cameras)) == 1]:
        if not corroborated(d):
            log.info("IGNORED: only cam%d saw %s and the other camera saw nothing new: not billed",
                     d.cameras[0], d.label)
            out.remove(d)
    # A lone unknown (one camera, no name) in a settle whose hand-in was for something else (an item taken
    # out, another put in, a late view) is the kind of glimpse that goes away: hold it for the recheck.
    if placement is not None:
        busy = len(out) > 1 or placement_used or any(i.placement == placement for i in cart.instances.values())
        for d in out:
            if d.kind == "added" and d.product_id is None and len(set(d.cameras)) == 1 and busy:
                log.info("HELD: cam%d's %s came with another item's hand-in: waiting %.0f s before billing it",
                         d.cameras[0], d.label, cfg.intrusion_recheck_s)
                d.kind = "held"
    # Out before in: a box taken out and another put in within one settle must never show as two at once
    # (with quantity nudges, that would be "two boxes… keep the extra?").
    return sorted(out, key=lambda d: {"removed": 0, "moved": 1}.get(d.kind, 2))


def still_there(blob: Blob, result: ChangeResult, empty: np.ndarray, cart: CartMemory, cfg) -> bool:
    """Is something (not bare floor) still lying where this blob was, in result's frame?"""
    cur, _, m = gain_matched(result, empty, cfg.roi.get(str(blob.cam)), cart)
    core = blob.core_box
    if _covered(_crop(cur, core), _crop(empty, core), _crop(m, core) if m is not None else None, cfg) < cfg.empty_share:
        return False
    return not _bare_liner(cur, core, m, liner_model(empty, m))


def apply_decision(cart: CartMemory, d: Decision) -> Instance | None:
    if d.kind == "added":
        return cart.add(d.product_id, d.label, d.views, d.awaiting, personal=d.personal, placement=d.placement)
    if d.kind == "removed":
        return cart.remove(d.instance_id) if d.instance_id in cart.instances else None
    if d.kind == "moved":
        cart.update_views(d.instance_id, d.views, d.placement)
        return cart.instances[d.instance_id]
    return None
