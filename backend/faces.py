"""Face detection + embedding (InsightFace buffalo_l via ONNX Runtime).

Runs on CUDA (Windows/Linux, if CUDA 13 + cuDNN 9 are installed), CoreML
(macOS), or CPU. Set PM_PROVIDER=cpu to force CPU.
"""
from __future__ import annotations

import os
import warnings

# insightface calls a scikit-image API deprecated in 0.26; harmless noise on every face.
warnings.filterwarnings("ignore", category=FutureWarning, module="insightface")
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

# Large scans are downscaled to this long side before detection. Big enough to
# keep small faces in group shots, small enough to stay fast.
MAX_SIDE = 3000
DEFAULT_DET_SIZE = 1024


@dataclass
class DetectedFace:
    bbox: tuple[float, float, float, float]  # normalized x1, y1, x2, y2
    det_score: float
    embedding: np.ndarray                     # float32[512], L2-normalized
    candidate: bool = False                   # found only by an extra pass: needs a human check


def _providers() -> list[str] | None:
    if os.environ.get("PM_PROVIDER", "").lower() == "cpu":
        return ["CPUExecutionProvider"]
    import onnxruntime as ort
    available = ort.get_available_providers()
    if "CUDAExecutionProvider" in available:
        # Check before preload_dlls(): it prints a wall of "Failed to load" when CUDA is absent.
        if _cuda_usable():
            try:
                ort.preload_dlls()
            except Exception:
                pass
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]
    return None  # let insightface pick (CoreML on macOS)


def _cuda_usable() -> bool:
    """onnxruntime-gpu lists CUDA even when its DLLs are missing; check for real."""
    import ctypes
    import sys
    if sys.platform != "win32":
        return True
    # The nvidia-* pip wheels put their DLLs under site-packages/nvidia/**/bin, off PATH.
    try:
        import nvidia
        for base in nvidia.__path__:
            for dll in {d.parent for d in Path(base).rglob("*64_*.dll")}:
                os.add_dll_directory(str(dll))
    except ImportError:
        pass  # fall back to a system CUDA install on PATH
    try:
        ctypes.WinDLL("cudart64_13.dll")
        ctypes.WinDLL("cudnn64_9.dll")
        return True
    except OSError:
        return False


@lru_cache(maxsize=4)
def get_app(det_size: int = DEFAULT_DET_SIZE, det_thresh: float = 0.5):
    from insightface.app import FaceAnalysis
    providers = _providers()
    kwargs = {"providers": providers} if providers else {}
    app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"], **kwargs)
    ctx = 0 if providers and providers[0] == "CUDAExecutionProvider" else -1
    app.prepare(ctx_id=ctx, det_thresh=det_thresh, det_size=(det_size, det_size))
    return app


def active_provider() -> str:
    app = get_app()
    return next(iter(app.models.values())).session.get_providers()[0]


def load_image(path: Path, max_side: int = MAX_SIDE) -> Image.Image:
    """Open any Pillow-readable image, apply EXIF rotation, return RGB."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    return img.convert("RGB")


def is_grayscale(img: Image.Image, tol: float = 6.0) -> bool:
    """True for black-and-white (incl. sepia-ish faded) scans. Used to split metrics."""
    small = np.asarray(img.resize((128, 128))).astype(np.float32)
    chroma = np.abs(small - small.mean(axis=2, keepdims=True)).mean()
    return bool(chroma < tol)


def _clahe(bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge((l, a, b)), cv2.COLOR_LAB2BGR)


# Tilted heads (lying down, leaning in) score below the detector's threshold until
# the image is turned. Fast mode tries these only when nothing is found upright;
# thorough mode always runs them all.
RETRY_ANGLES = (30, -30, 60, -60, 90, -90)
# Thorough mode also runs the detector at this larger input size (small faces in groups).
THOROUGH_DET_SIZE = 1600


def _rotate(bgr: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray]:
    """Rotate counter-clockwise on an expanded canvas. Returns the image and the
    affine transform mapping its pixels back to the original."""
    h, w = bgr.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos), int(h * cos + w * sin)
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(bgr, m, (nw, nh)), cv2.invertAffineTransform(m)


def _upright_box(bbox, back: np.ndarray) -> tuple[float, float, float, float]:
    """Box found in a rotated image -> same-size box around its centre in the original."""
    x1, y1, x2, y2 = (float(v) for v in bbox)
    cx, cy = back @ np.array([(x1 + x2) / 2, (y1 + y2) / 2, 1.0])
    half = ((x2 - x1) + (y2 - y1)) / 4
    return cx - half, cy - half, cx + half, cy + half


def same_face(a, b) -> bool:
    """Two boxes (any one coordinate system) cover the same face: either centre lies inside the other."""
    def inside(p, q):
        cx, cy = (p[0] + p[2]) / 2, (p[1] + p[3]) / 2
        return q[0] <= cx <= q[2] and q[1] <= cy <= q[3]
    return inside(a, b) or inside(b, a)


def detect(img: Image.Image, det_size: int = DEFAULT_DET_SIZE,
           clahe_retry: bool = True, thorough: bool = True,
           enlarged: bool = True, rotated: bool = True) -> list[DetectedFace]:
    """Detect and embed faces.

    thorough=True (default) runs several passes and merges them: upright, contrast-enhanced
    (faded prints), a larger detector size (small faces) and every angle in RETRY_ANGLES
    (tilted heads). About 8x the work of a single pass - worth it when a missed face
    is worse than a slow scan. thorough=False stops at the first pass that finds anything.
    clahe_retry / enlarged / rotated switch individual extra passes off."""
    bgr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    app = get_app(det_size)
    found: list[tuple] = []  # (box in original pixels, insightface Face, extra pass?); first wins

    def add(faces, boxes, extra: bool) -> None:
        for f, b in zip(faces, boxes):
            if not any(same_face(b, other) for other, _, _ in found):
                found.append((tuple(float(v) for v in b), f, extra))

    def upright(a, image, extra: bool):
        fs = a.get(image)
        add(fs, [f.bbox for f in fs], extra)

    upright(app, bgr, extra=False)
    if clahe_retry and (thorough or not found):
        upright(app, _clahe(bgr), extra=True)
    if thorough and enlarged:
        upright(get_app(THOROUGH_DET_SIZE), bgr, extra=True)
    for angle in RETRY_ANGLES if rotated else ():
        if found and not thorough:
            break
        turned, back = _rotate(bgr, angle)
        fs = app.get(turned)
        add(fs, [_upright_box(f.bbox, back) for f in fs], extra=True)

    h, w = bgr.shape[:2]
    out = []
    for (x1, y1, x2, y2), f, extra in found:
        out.append(DetectedFace(
            bbox=(max(0.0, x1 / w), max(0.0, y1 / h), min(1.0, x2 / w), min(1.0, y2 / h)),
            det_score=float(f.det_score),
            embedding=f.normed_embedding.astype(np.float32),
            candidate=extra,
        ))
    return out


def crop_face(img: Image.Image, bbox: tuple[float, float, float, float],
              size: int = 160, margin: float = 0.25) -> Image.Image:
    """Square thumbnail around a normalized bbox, with some context."""
    w, h = img.size
    x1, y1, x2, y2 = bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    side = max(x2 - x1, y2 - y1) * (1 + 2 * margin)
    box = (int(cx - side / 2), int(cy - side / 2), int(cx + side / 2), int(cy + side / 2))
    return img.crop(box).resize((size, size), Image.LANCZOS)
