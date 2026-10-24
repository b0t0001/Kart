import base64
import json
from types import SimpleNamespace as NS

import anthropic
import cv2
import numpy as np

from kartcv.catalog import Catalog, Product
from kartcv.config import Config
from kartcv.identify.cloud import CloudAnswer, CloudIdentifier
from kartcv.identify.hybrid import HybridIdentifier, Identification

CAT = Catalog({p.id: p for p in [Product("kirkland-parmesan", "Kirkland Parmigiano Reggiano", 12.99, "wedge"),
                                 Product("rao-marinara", "Rao's Marinara", 6.99, "jar")]})
CROP = np.full((300, 400, 3), 128, np.uint8)


def _req():
    try:
        import httpx2 as httpx
    except ImportError:
        import httpx
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeClient:
    def __init__(self, text=None, stop="end_turn", exc=None):
        self.text, self.stop, self.exc, self.kwargs, self.options = text, stop, exc, None, None
        self.messages = self

    def with_options(self, **kw):
        self.options = kw
        return self

    def create(self, **kw):
        self.kwargs = kw
        if self.exc:
            raise self.exc
        return NS(stop_reason=self.stop, content=[NS(type="text", text=self.text)])


def ans(pid, conf=0.8, label="x"):
    return json.dumps({"product_id": pid, "confidence": conf, "label": label})


def test_request_shape():
    fc = FakeClient(ans("kirkland-parmesan"))
    CloudIdentifier(CAT, "claude-haiku-5-5", 6.0, client=fc).identify([CROP] * 6)
    kw = fc.kwargs
    content = kw["messages"][0]["content"]
    imgs = [b for b in content if b["type"] == "image"]
    assert kw["model"] == "claude-haiku-5-5" and fc.options == {"timeout": 6.0, "max_retries": 0} and len(imgs) == 2
    assert imgs[0]["source"]["media_type"] == "image/jpeg" and content[-1]["type"] == "text"
    assert "rao-marinara | Rao's Marinara | jar" in content[-1]["text"]
    schema = kw["output_config"]["format"]["schema"]
    assert set(schema["properties"]["product_id"]["enum"]) == {"kirkland-parmesan", "rao-marinara", "unknown"}
    assert kw["output_config"]["effort"] == "low"


def test_images_downscaled():
    fc = FakeClient(ans("unknown"))
    CloudIdentifier(CAT, "m", 3.0, client=fc).identify([np.zeros((900, 1200, 3), np.uint8)])
    data = base64.b64decode(fc.kwargs["messages"][0]["content"][0]["source"]["data"])
    assert max(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR).shape[:2]) <= 512


def test_answers_and_failures():  # Review Focus 5
    def run(**kw):
        return CloudIdentifier(CAT, "m", 3.0, client=FakeClient(**kw)).identify([CROP])

    assert run(text=ans("kirkland-parmesan", 0.82, "parm")) == CloudAnswer("kirkland-parmesan", 0.82, "parm")
    assert run(text=ans("unknown", 0.3, "a can")).product_id is None
    assert run(text=ans("made-up", 0.9)).product_id is None
    assert run(text="not json").product_id is None
    assert run(text=ans("rao-marinara"), stop="refusal").product_id is None
    assert run(exc=anthropic.APITimeoutError(request=_req())).product_id is None
    assert run(exc=anthropic.APIConnectionError(request=_req())).product_id is None


class FakeGallery:
    def __init__(self, ranked):
        self.ranked = ranked

    def score(self, crops):
        return self.ranked


class FakeCloud:
    def __init__(self, answer):
        self.answer, self.calls = answer, 0

    def identify(self, crops):
        self.calls += 1
        return self.answer


def hyb(ranked, cloud):
    return HybridIdentifier(FakeGallery(ranked), cloud, CAT, Config()).identify([CROP])


def test_hybrid_policy():
    c = FakeCloud(CloudAnswer("rao-marinara", 0.9, "jar"))
    assert hyb([("kirkland-parmesan", 0.9), ("rao-marinara", 0.7)], c) == \
        Identification("kirkland-parmesan", 0.9, "local", "Kirkland Parmigiano Reggiano") and c.calls == 0
    assert hyb([("kirkland-parmesan", 0.85)], c).method == "local"
    assert hyb([("kirkland-parmesan", 0.80), ("rao-marinara", 0.76)], c) == \
        Identification("rao-marinara", 0.9, "cloud", "Rao's Marinara")
    assert hyb([("kirkland-parmesan", 0.6)], c).method == "cloud" and hyb([], c).method == "cloud"
    assert hyb([("kirkland-parmesan", 0.6)], FakeCloud(CloudAnswer("rao-marinara", 0.4, "maybe jar"))) == \
        Identification(None, 0.6, "none", "maybe jar")
    assert hyb([("kirkland-parmesan", 0.6)], None) == Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")
    assert hyb([("gone-product", 0.95), ("kirkland-parmesan", 0.6)], None) == \
        Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")
