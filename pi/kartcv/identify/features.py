"""Crop → fingerprint (L2-normalized float32 vector). ONNX CNN embedding, or a color histogram fallback."""
from __future__ import annotations

import logging
import tempfile
import urllib.request
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

log = logging.getLogger(__name__)

MOBILENET_URL = ("https://github.com/onnx/models/raw/main/validated/vision/classification/"
                 "mobilenet/model/mobilenetv2-12.onnx")
_MEAN = np.float32([0.485, 0.456, 0.406])
_STD = np.float32([0.229, 0.224, 0.225])


class FeatureExtractor(Protocol):
    name: str

    def __call__(self, crop_bgr: np.ndarray) -> np.ndarray: ...


def _l2(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


class HistogramFeatures:
    """HSV 8×8×4 histogram, square-rooted (Hellinger) and L2-normalized: 256-d."""

    name = "hist"

    def __call__(self, crop_bgr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [8, 8, 4], [0, 180, 0, 256, 0, 256])
        return _l2(np.sqrt(hist))


class OnnxFeatures:
    """ImageNet-pretrained CNN embedding (MobileNetV2 pooled features, 1280-d) via onnxruntime."""

    def __init__(self, model_path: Path):
        import onnxruntime as ort

        self.name = f"onnx:{Path(model_path).stem}"
        self._session = ort.InferenceSession(str(model_path), providers=["CPUExecutionProvider"])
        self._input = self._session.get_inputs()[0].name

    def __call__(self, crop_bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(cv2.resize(crop_bgr, (224, 224), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
        x = (rgb.astype(np.float32) / 255.0 - _MEAN) / _STD
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        return _l2(self._session.run(None, {self._input: x})[0])


def load_features(model_path: Path, kind: str = "auto") -> FeatureExtractor:
    if kind == "hist":
        return HistogramFeatures()
    if Path(model_path).exists():
        try:
            return OnnxFeatures(model_path)
        except Exception as e:  # onnxruntime missing or the file is broken: keep running on histograms
            log.warning("features: could not load %s (%s); using color histograms", model_path, e)
    else:
        log.warning("features: %s not found (run tools/fetch_model.py); using color histograms", model_path)
    return HistogramFeatures()


def fetch_model(dest: Path, url: str = MOBILENET_URL) -> Path:
    """Download MobileNetV2 and cut it at the last GlobalAveragePool so it outputs a 1280-d embedding."""
    import onnx
    import onnx.utils
    import onnxruntime as ort

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "mobilenetv2.onnx"
        urllib.request.urlretrieve(url, raw)
        model = onnx.load(str(raw))
        initializers = {i.name for i in model.graph.initializer}
        input_name = next(i.name for i in model.graph.input if i.name not in initializers)
        pooled = [n for n in model.graph.node if n.op_type == "GlobalAveragePool"][-1].output[0]
        onnx.utils.extract_model(str(raw), str(dest), [input_name], [pooled])
    session = ort.InferenceSession(str(dest), providers=["CPUExecutionProvider"])
    out = session.run(None, {session.get_inputs()[0].name: np.zeros((1, 3, 224, 224), np.float32)})[0]
    if out.size != 1280:
        raise RuntimeError(f"unexpected embedding size {out.size} from {dest}")
    return dest
