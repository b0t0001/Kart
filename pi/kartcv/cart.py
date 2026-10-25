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
    # spots where another camera's view of this unit was held back when it was billed (an arm was in the
    # way): that camera's next look there is this unit, seen late, not a second one
    awaiting: dict[int, list] = field(default_factory=dict)
    personal: bool = False  # the shopper's own belonging: tracked so its removal is silent, never billed
    placement: str = ""  # the hand-in that brought it (pipeline run : count): one placement, one unit of a product


class CartMemory:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.instances: dict[str, Instance] = {}

    # --- mutations (each one saves) ---
    def add(self, product_id: str | None, label: str, views: dict[int, View], awaiting: dict | None = None,
            personal: bool = False, placement: str = "") -> Instance:
        views = {c: View(v.cam, tuple(v.box), list(v.fingerprint), v.crop_path) for c, v in views.items()}  # own copies
        inst = Instance(uuid.uuid4().hex, product_id, label, utc_now_iso(), views,
                        awaiting={int(c): [tuple(b) for b in bs] for c, bs in (awaiting or {}).items()},
                        personal=personal, placement=placement)
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
        inst = self.instances[instance_id]
        inst.views.update(views)
        for c in views:
            inst.awaiting.pop(c, None)
        self.save()

    def mark_personal(self, event_id: str) -> bool:
        """The shopper said the unit billed by this event is theirs ("that's mine")."""
        inst = next((i for i in self.instances.values() if event_id and i.event_id == event_id), None)
        if inst is None:
            return False
        inst.personal = True
        self.save()
        return True

    def expire_awaiting(self, cams) -> None:
        """Those cameras had a clean look: any late view of an earlier unit would have shown up by now."""
        changed = False
        for inst in self.instances.values():
            for c in cams:
                changed |= inst.awaiting.pop(c, None) is not None
        if changed:
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
                                d.get("event_id", ""),
                                {int(c): [tuple(b) for b in bs] for c, bs in d.get("awaiting", {}).items()},
                                bool(d.get("personal", False)), str(d.get("placement", "")))
                mem.instances[inst.instance_id] = inst
        return mem
