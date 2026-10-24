"""What the cart believes is inside it, and where each camera saw it (spec §7). Persisted on every change."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from kartcv.events import utc_now_iso


@dataclass
class View:
    cam: int
    box: tuple[int, int, int, int]  # x, y, w, h in that camera's full-res pixels
    fingerprint: list[float]
    crop_path: str = ""


@dataclass
class Instance:
    instance_id: str
    product_id: str | None
    label: str
    added_ts: str
    views: dict[int, View] = field(default_factory=dict)
    event_id: str = ""  # the "added" event this unit was billed by


class CartMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.instances: dict[str, Instance] = {}

    # --- mutations (each one saves) ---
    def add(self, product_id: str | None, label: str, views: dict[int, View]) -> Instance:
        inst = Instance(uuid.uuid4().hex, product_id, label, utc_now_iso(), dict(views))
        self.instances[inst.instance_id] = inst
        self.save()
        return inst

    def remove(self, instance_id: str) -> Instance:
        inst = self.instances.pop(instance_id)
        self.save()
        return inst

    def set_event_id(self, instance_id: str, event_id: str) -> None:
        self.instances[instance_id].event_id = event_id
        self.save()

    def update_views(self, instance_id: str, views: dict[int, View]) -> None:
        self.instances[instance_id].views.update(views)
        self.save()

    def shift_views(self, cam: int, dx: float, dy: float) -> None:
        for inst in self.instances.values():
            v = inst.views.get(cam)
            if v is not None:
                x, y, w, h = v.box
                v.box = (int(round(x + dx)), int(round(y + dy)), w, h)
        self.save()

    def clear(self) -> None:
        self.instances.clear()
        self.save()

    # --- queries ---
    def views_in(self, cam: int) -> list[tuple[Instance, View]]:
        return [(i, i.views[cam]) for i in self.instances.values() if cam in i.views]

    def count(self, product_id: str | None) -> int:
        return sum(1 for i in self.instances.values() if i.product_id == product_id)

    # --- persistence ---
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"instances": [asdict(i) for i in self.instances.values()]}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, self.path)

    @classmethod
    def load(cls, path: Path) -> CartMemory:
        mem = cls(path)
        if mem.path.exists():
            for d in json.loads(mem.path.read_text())["instances"]:
                views = {int(c): View(int(v["cam"]), tuple(v["box"]), list(v["fingerprint"]), v.get("crop_path", ""))
                         for c, v in d["views"].items()}
                inst = Instance(d["instance_id"], d["product_id"], d["label"], d["added_ts"], views,
                                d.get("event_id", ""))
                mem.instances[inst.instance_id] = inst
        return mem
