"""Closed-set identification with Claude: crops + catalog in, one product id (or unknown) out (spec §6.1)."""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass

import anthropic
import cv2
import numpy as np

log = logging.getLogger(__name__)

MAX_CROPS = 4
MAX_SIDE = 512

SYSTEM = (
    "You identify grocery items in a smart shopping cart. Every photo is a crop of the SAME single item, "
    "seen from different cameras mounted on the cart. Pick the one catalog product it is, using the name and "
    "the visual description. If it is not clearly one of them, answer \"unknown\". "
    "confidence is your probability (0 to 1) that the product_id is right; label is a few plain words "
    "describing what you see."
)


@dataclass
class CloudAnswer:
    product_id: str | None
    confidence: float
    label: str


def _jpeg_b64(crop: np.ndarray) -> str:
    h, w = crop.shape[:2]
    scale = MAX_SIDE / max(h, w)
    if scale < 1.0:
        crop = cv2.resize(crop, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buf.tobytes()).decode("ascii")


class CloudIdentifier:
    def __init__(self, catalog, model: str, timeout_s: float, client=None):
        self.catalog = catalog
        self.model = model
        self.timeout_s = timeout_s
        self._client = client if client is not None else anthropic.Anthropic()

    def _schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "product_id": {"type": "string", "enum": self.catalog.ids() + ["unknown"]},
                "confidence": {"type": "number"},
                "label": {"type": "string"},
            },
            "required": ["product_id", "confidence", "label"],
            "additionalProperties": False,
        }

    def identify(self, crops: list[np.ndarray]) -> CloudAnswer:
        """Never raises: any failure is an unknown answer, so the cart loop can't stall or crash."""
        images = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _jpeg_b64(c)}}
                  for c in crops[:MAX_CROPS]]
        text = {"type": "text", "text": "Catalog (id | name | what it looks like):\n" + self.catalog.prompt_lines()}
        try:
            resp = self._client.with_options(timeout=self.timeout_s, max_retries=0).messages.create(
                model=self.model,
                max_tokens=1024,
                system=SYSTEM,
                messages=[{"role": "user", "content": images + [text]}],
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": self._schema()}},
            )
        except anthropic.APITimeoutError:
            log.warning("cloud: Claude timed out after %.1f s", self.timeout_s)
            return CloudAnswer(None, 0.0, "error: timeout")
        except anthropic.APIConnectionError as e:
            log.warning("cloud: connection error (%s)", e)
            return CloudAnswer(None, 0.0, "error: connection")
        except anthropic.APIStatusError as e:
            log.warning("cloud: HTTP %s from Claude", e.status_code)
            return CloudAnswer(None, 0.0, f"error: http {e.status_code}")

        if resp.stop_reason == "refusal":
            return CloudAnswer(None, 0.0, "error: refusal")
        body = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        try:
            data = json.loads(body or "")
            pid = data.get("product_id")
            conf = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
            label = str(data.get("label", ""))
        except (ValueError, TypeError, AttributeError):
            return CloudAnswer(None, 0.0, "error: bad answer")
        if pid == "unknown" or self.catalog.get(pid) is None:
            return CloudAnswer(None, conf, label or "unknown")
        return CloudAnswer(pid, conf, label)
