"""Калибровка WILDTRACK: проекция точек земли в кадр и обратно (луч до плоскости Z=0).

Мировые координаты в сантиметрах, начало сетки (-300, -900), шаг сетки 2.5 см, 480×1440 ячеек.
Номер камеры = индекс в NAMES + 1 (C1 = CVLab1 ... C5 = IDIAP1 ... C7 = IDIAP3).
"""
import re
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "data" / "TestDataset1"
OUT = ROOT / "data" / "output"

NAMES = ["CVLab1", "CVLab2", "CVLab3", "CVLab4", "IDIAP1", "IDIAP2", "IDIAP3"]
IMG_W, IMG_H = 1920, 1080

# Область земли, которую размечал датасет (см).
X_MIN, X_MAX = -300.0, 900.0
Y_MIN, Y_MAX = -900.0, 2700.0


def _numbers(path: Path, tag: str) -> np.ndarray:
    text = path.read_text()
    body = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.S).group(1)
    return np.array([float(x) for x in re.sub(r"<[^>]+>", " ", body).split()])


def _rodrigues(r: np.ndarray) -> np.ndarray:
    theta = np.linalg.norm(r)
    if theta < 1e-12:
        return np.eye(3)
    k = r / theta
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + np.sin(theta) * kx + (1 - np.cos(theta)) * kx @ kx


class Camera:
    def __init__(self, index: int):
        self.index = index  # 0..6
        name = NAMES[index]
        ext = DATASET / "calibrations" / "extrinsic" / f"extr_{name}.xml"
        # Кадры датасета уже без дисторсии, поэтому берём intrinsic_zero.
        intr = DATASET / "calibrations" / "intrinsic_zero" / f"intr_{name}.xml"
        self.R = _rodrigues(_numbers(ext, "rvec"))
        self.t = _numbers(ext, "tvec")
        self.K = _numbers(intr, "data")[:9].reshape(3, 3)
        self.Kinv = np.linalg.inv(self.K)
        self.center = -self.R.T @ self.t  # положение камеры в мире, см

    def project(self, pts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """pts: (N,3) в мире -> пиксели (N,2) и глубина z (N,)."""
        cam = pts @ self.R.T + self.t
        z = cam[:, 2]
        uv = cam @ self.K.T
        with np.errstate(divide="ignore", invalid="ignore"):
            return uv[:, :2] / uv[:, 2:3], z

    def to_ground(self, uv: np.ndarray, height: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
        """Пиксели (N,2) -> точки на плоскости Z=height (N,2) и маска «луч дошёл до плоскости»."""
        pix = np.concatenate([uv, np.ones((len(uv), 1))], axis=1)
        d = pix @ self.Kinv.T @ self.R  # направление луча в мире (R^T применяется справа)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = (height - self.center[2]) / d[:, 2]
        ok = np.isfinite(s) & (s > 0)
        xy = self.center[:2] + d[:, :2] * s[:, None]
        return xy, ok


def load_cameras() -> list[Camera]:
    return [Camera(i) for i in range(7)]


# ---- видео ------------------------------------------------------------------------------
# Видео сняты с дисторсией объектива, а калибровка (intrinsic_zero) и разметка относятся к исправленным
# кадрам. Поэтому каждый кадр видео сначала исправляем, после чего вся геометрия общая.
# Временная шкала: t секунд = кадр round(t*60) + сдвиг камеры (измеряет sync.py).

TIMELINE_FPS = 60.0


def undistort_maps(cam_index: int):
    import cv2

    name = NAMES[cam_index]
    fs = cv2.FileStorage(str(DATASET / "calibrations" / "intrinsic_original" / f"intr_{name}.xml"), cv2.FILE_STORAGE_READ)
    k_orig, dist = fs.getNode("camera_matrix").mat(), fs.getNode("distortion_coefficients").mat()
    fs.release()
    k_zero = Camera(cam_index).K
    return cv2.initUndistortRectifyMap(k_orig, dist, None, k_zero, (IMG_W, IMG_H), cv2.CV_16SC2)


def load_offsets() -> list[int]:
    import json

    path = OUT / "sync.json"
    if not path.exists():
        return [0] * 7
    return json.loads(path.read_text())["offsets_frames"]


def frame_index(t: float, cam_index: int, offsets: list[int]) -> int:
    return round(t * TIMELINE_FPS) + offsets[cam_index]


def position_id_to_xy(pid: np.ndarray | int) -> np.ndarray:
    pid = np.asarray(pid)
    return np.stack([-300.0 + 2.5 * (pid % 480), -900.0 + 2.5 * (pid // 480)], axis=-1)
