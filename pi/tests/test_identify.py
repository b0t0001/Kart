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
    # one quick retry: a hotspot hiccup (one call took 9.5 s) gets a second chance instead of "unknown"
    assert kw["model"] == "claude-haiku-5-5" and fc.options == {"timeout": 6.0, "max_retries": 1} and len(imgs) == 2
    assert imgs[0]["source"]["media_type"] == "image/jpeg" and content[-1]["type"] == "text"
    assert "rao-marinara | Rao's Marinara | jar" in content[-1]["text"]
    schema = kw["output_config"]["format"]["schema"]
    assert set(schema["properties"]["product_id"]["enum"]) == {"kirkland-parmesan", "rao-marinara", "unknown"}
    assert kw["output_config"]["effort"] == "low"
    assert "thinking" not in kw  # model default: off saved ~0.3 s but put the marinara on the 0.6 line


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
        Identification(None, 0.6, "none", "maybe jar", asked=True)  # Claude looked: a real verdict
    assert not hyb([], FakeCloud(CloudAnswer(None, 0.0, "error: timeout"))).asked  # a timeout is none
    assert hyb([("kirkland-parmesan", 0.6)], None) == Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")
    assert hyb([("gone-product", 0.95), ("kirkland-parmesan", 0.6)], None) == \
        Identification(None, 0.6, "none", "Kirkland Parmigiano Reggiano")


def ans_n(pid, n, conf=0.9):
    return json.dumps({"product_id": pid, "confidence": conf, "label": "x", "count": n})


def test_count_is_off_by_default():  # claude_count: false = the stable behavior
    fc = FakeClient(ans_n("rao-marinara", 3))
    a = CloudIdentifier(CAT, "m", 6.0, client=fc).identify([CROP])
    assert "count" not in fc.kwargs["output_config"]["format"]["schema"]["properties"] and a.count == 1


def test_a_multipack_counts_as_one_package():  # kids-scissors: one 2 ct pack is ONE item
    fc = FakeClient(ans_n("rao-marinara", 1))
    CloudIdentifier(CAT, "m", 6.0, client=fc, count=True).identify([CROP])
    assert "packages, not what is inside them" in fc.kwargs["system"]


def test_count_when_enabled():
    fc = FakeClient(ans_n("rao-marinara", 3))
    a = CloudIdentifier(CAT, "m", 6.0, client=fc, count=True).identify([CROP])
    props = fc.kwargs["output_config"]["format"]["schema"]["properties"]
    assert props["count"]["enum"] == [1, 2, 3, 4, 5, 6] and "count" in fc.kwargs["output_config"]["format"]["schema"]["required"]
    assert a == CloudAnswer("rao-marinara", 0.9, "x", 3)
    assert CloudIdentifier(CAT, "m", 6.0, client=FakeClient(ans_n("rao-marinara", 40)), count=True).identify([CROP]).count == 6
    assert CloudIdentifier(CAT, "m", 6.0, client=FakeClient(ans_n("rao-marinara", "many")), count=True).identify([CROP]).count == 1


class SizedGallery(FakeGallery):
    def typical_area(self, pid):
        return 30_000  # enrolled single-unit crops are ~4x smaller than CROP (120,000 px)


def test_oversized_blob_asks_claude_for_the_count_only_with_the_flag():
    from kartcv.config import Config as C
    c = FakeCloud(CloudAnswer("kirkland-parmesan", 0.9, "two wedges", 2))
    on = HybridIdentifier(SizedGallery([("kirkland-parmesan", 0.95)]), c, CAT, C(claude_count=True)).identify([CROP])
    assert (on.product_id, on.method, on.count, c.calls) == ("kirkland-parmesan", "cloud", 2, 1)
    c2 = FakeCloud(CloudAnswer("kirkland-parmesan", 0.9, "two wedges", 2))
    off = HybridIdentifier(SizedGallery([("kirkland-parmesan", 0.95)]), c2, CAT, C()).identify([CROP])
    assert (off.method, off.count, c2.calls) == ("local", 1, 0)


def test_personal_is_offered_only_with_the_flag():
    fc = FakeClient(ans("personal", 0.9, "black leather purse"))
    off = CloudIdentifier(CAT, "m", 6.0, client=fc).identify([CROP])
    assert "personal" not in fc.kwargs["output_config"]["format"]["schema"]["properties"]["product_id"]["enum"]
    assert off.product_id is None and not off.personal
    fc = FakeClient(ans("personal", 0.9, "black leather purse"))
    on = CloudIdentifier(CAT, "m", 6.0, client=fc, personal=True).identify([CROP])
    assert "personal" in fc.kwargs["output_config"]["format"]["schema"]["properties"]["product_id"]["enum"]
    assert (on.product_id, on.personal, on.label) == (None, True, "black leather purse")


def test_hybrid_can_be_told_not_to_use_the_cloud():
    c = FakeCloud(CloudAnswer("rao-marinara", 0.9, "jar"))
    r = HybridIdentifier(FakeGallery([("kirkland-parmesan", 0.6)]), c, CAT, Config()).identify([CROP], allow_cloud=False)
    assert (r.product_id, r.method, c.calls) == (None, "none", 0)
