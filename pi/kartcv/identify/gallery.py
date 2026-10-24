"""Few-shot gallery: enrolled crops per product, scored by nearest neighbours (spec §6.1, §6.3)."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

TOP_K = 3


class Gallery:
    """Photos live in root/<product_id>/NNN.jpg; fingerprints are cached in root/index.npz."""

    def __init__(self, root: Path, features):
        self.root = Path(root)
        self.features = features
        self._paths: list[Path] = []
        self._pids: list[str] = []
        self._areas: list[int] = []  # crop size (px) of each photo: one enrolled unit's footprint
        self._vecs = np.zeros((0, 0), np.float32)

    @property
    def _index(self) -> Path:
        return self.root / "index.npz"

    def load(self) -> None:
        cache: dict[str, tuple[float, np.ndarray]] = {}
        if self._index.exists():
            data = np.load(self._index, allow_pickle=False)
            if str(data["features"]) == self.features.name and "areas" in data:
                for rel, mtime, vec, area in zip(data["paths"], data["mtimes"], data["vectors"], data["areas"]):
                    cache[str(rel)] = (float(mtime), vec, int(area))
        paths, pids, vecs, areas = [], [], [], []
        for p in sorted(self.root.glob("*/*.jpg")):
            if p.parent.name.startswith("."):
                continue
            rel, mtime = p.relative_to(self.root).as_posix(), p.stat().st_mtime
            if rel in cache and cache[rel][0] == mtime:
                vec, area = cache[rel][1], cache[rel][2]
            else:
                img = cv2.imread(str(p), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                vec, area = self.features(img), img.shape[0] * img.shape[1]
            paths.append(p)
            pids.append(p.parent.name)
            vecs.append(vec)
            areas.append(area)
        self._paths, self._pids, self._areas = paths, pids, areas
        self._vecs = np.stack(vecs).astype(np.float32) if vecs else np.zeros((0, 0), np.float32)
        self._save_index()

    def _save_index(self) -> None:
        if not self._paths:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        np.savez(self._index,
                 paths=np.array([p.relative_to(self.root).as_posix() for p in self._paths]),
                 mtimes=np.array([p.stat().st_mtime for p in self._paths]),
                 vectors=self._vecs,
                 areas=np.array(self._areas),
                 features=np.array(self.features.name))

    def add(self, product_id: str, crop: np.ndarray) -> Path:
        d = self.root / product_id
        d.mkdir(parents=True, exist_ok=True)
        taken = [int(p.stem) for p in d.glob("*.jpg") if p.stem.isdigit()]
        path = d / f"{(max(taken) + 1) if taken else 0:03d}.jpg"
        cv2.imwrite(str(path), crop)
        vec = self.features(cv2.imread(str(path), cv2.IMREAD_COLOR))  # embed what load() will see (post-JPEG)
        self._paths.append(path)
        self._pids.append(product_id)
        self._areas.append(crop.shape[0] * crop.shape[1])
        self._vecs = np.vstack([self._vecs, vec[None]]) if self._vecs.size else vec[None].astype(np.float32)
        self._save_index()
        return path

    def products(self) -> set[str]:
        return set(self._pids)

    def typical_area(self, product_id: str) -> float | None:
        """Median crop size (px) of one enrolled unit of this product, or None if not enrolled."""
        a = [ar for p, ar in zip(self._pids, self._areas) if p == product_id]
        return float(np.median(a)) if a else None

    def leave_one_out(self) -> dict:
        """How well the enrolled photos identify each other (each photo scored against all the others).

        top1 = share of photos whose best product is their own; median_margin = median lead of the true
        product over the runner-up (negative when wrong). Use it to compare feature extractors on the real
        props before switching `features` (local_min_margin is the lead the matcher demands).
        """
        pids = np.array(self._pids)
        products = sorted(set(self._pids))
        correct, margins = 0, []
        for i, pid in enumerate(self._pids):
            if (pids == pid).sum() < 2:
                continue  # nothing left to match against
            sims = self._vecs @ self._vecs[i]
            sims[i] = -np.inf
            scores = {}
            for p in products:
                col = np.sort(sims[(pids == p) & np.isfinite(sims)])[::-1][:TOP_K]
                if col.size:
                    scores[p] = float(col.mean())
            ranked = sorted(scores, key=lambda p: -scores[p])
            others = [scores[p] for p in ranked if p != pid]
            margins.append(scores[pid] - (others[0] if others else 0.0))
            correct += ranked[0] == pid
        n = len(margins)
        return {"images": len(self._pids), "products": len(products),
                "top1": correct / n if n else 0.0, "median_margin": float(np.median(margins)) if n else 0.0}

    def score(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        """Per product: mean of the top-3 cosine similarities, averaged over crops. Best first."""
        if not self._pids or not crops:
            return []
        q = np.stack([self.features(c) for c in crops])
        sims = q @ self._vecs.T  # (crops, examples)
        pids = np.array(self._pids)
        scores = []
        for pid in sorted(set(self._pids)):
            cols = sims[:, pids == pid]
            k = min(TOP_K, cols.shape[1])
            top = -np.sort(-cols, axis=1)[:, :k]
            scores.append((pid, float(top.mean(axis=1).mean())))
        return sorted(scores, key=lambda s: -s[1])
