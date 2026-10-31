"""Этап 3: картинки и видео для проверки глазами.

  python render.py --start 0 --seconds 60
Выход (data/output): territory.png, heatmap.png, counts.png, cams_mosaic.mp4, topdown.mp4, sheet_*.jpg
"""
import argparse
import pickle
import subprocess

import cv2
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

from calib import (DATASET, IMG_H, IMG_W, OUT, X_MAX, X_MIN, Y_MAX, Y_MIN, frame_index, load_cameras,  # noqa: E402
                   load_offsets, undistort_maps)
from fuse import CELL, NX, NY  # noqa: E402

GREEN, ORANGE, GRAY = (80, 220, 80), (0, 165, 255), (160, 160, 160)


def territory_contours(mask: np.ndarray) -> list[np.ndarray]:
    """Контуры территории в мировых координатах (см)."""
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        if len(c) < 3:
            continue
        pts = c[:, 0, :].astype(float)
        out.append(np.c_[X_MIN + (pts[:, 0] + 0.5) * CELL, Y_MIN + (pts[:, 1] + 0.5) * CELL])
    return out


def draw_territory(img: np.ndarray, cam, contours, scale: float) -> None:
    for c in contours:
        # плотная дискретизация, чтобы линия на земле не «срезала» углы в перспективе
        dense = np.concatenate([np.linspace(c[i], c[(i + 1) % len(c)], 6, endpoint=False) for i in range(len(c))])
        uv, z = cam.project(np.c_[dense, np.zeros(len(dense))])
        pts = (uv * scale).astype(np.int32)
        good = z > 0
        run: list = []
        for p, g in zip(pts, good):
            if g:
                run.append(p)
            elif len(run) > 1:
                cv2.polylines(img, [np.array(run)], False, (255, 220, 0), 2, cv2.LINE_AA)
                run = []
            else:
                run = []
        if len(run) > 1:
            cv2.polylines(img, [np.array(run)], len(run) == len(pts), (255, 220, 0), 2, cv2.LINE_AA)


def contour_territory(ax, terr: np.ndarray, color: str, lw: float = 1.5) -> None:
    """Контур с отступом в ячейку, чтобы граница рисовалась и вдоль краёв площадки."""
    padded = np.pad(terr.astype(float), 1)
    xs = (X_MIN + (np.arange(NX + 2) - 0.5) * CELL) / 100
    ys = (Y_MIN + (np.arange(NY + 2) - 0.5) * CELL) / 100
    ax.contour(xs, ys, padded, [0.5], colors=color, linewidths=lw)


def plots(data: dict, cams) -> None:
    frames, terr, ext, vis, fps = data["frames"], data["territory"], data["extended"], data["vis"], data["fps"]
    extent = [X_MIN / 100, X_MAX / 100, Y_MAX / 100, Y_MIN / 100]

    fig, ax = plt.subplots(figsize=(5, 10))
    im = ax.imshow(vis, extent=extent, cmap="viridis", vmin=0, vmax=7)
    contour_territory(ax, terr, "red")
    for i, c in enumerate(cams):
        ax.plot(c.center[0] / 100, c.center[1] / 100, "w^", ms=10, mec="k")
        ax.annotate(f"C{i + 1}", (c.center[0] / 100, c.center[1] / 100), color="w", fontsize=9, xytext=(4, 4),
                    textcoords="offset points")
    ax.set_title("Сколько камер видят точку (красная линия — территория)")
    fig.colorbar(im, ax=ax, shrink=0.5, label="камер")
    ax.set_xlabel("X, м"); ax.set_ylabel("Y, м")
    fig.tight_layout(); fig.savefig(OUT / "territory.png", dpi=110); plt.close(fig)

    # тепловая карта по всем подтверждённым людям внутри видимой области
    cell = 25.0
    hx, hy = int((X_MAX - X_MIN) / cell), int((Y_MAX - Y_MIN) / cell)
    heat = np.zeros((hy, hx))
    for fr in frames:
        for p in fr:
            ix, iy = int((p["x"] - X_MIN) / cell), int((p["y"] - Y_MIN) / cell)
            if 0 <= ix < hx and 0 <= iy < hy:
                heat[iy, ix] += 1
    heat = gaussian_filter(heat, 2.0)
    np.save(OUT / "heat.npy", heat)
    fig, ax = plt.subplots(figsize=(5, 10))
    ax.imshow(ext, extent=extent, cmap="gray_r", alpha=0.15)
    m = np.ma.masked_less(heat, heat.max() * 0.02)
    im = ax.imshow(m, extent=extent, cmap="jet", alpha=0.8)
    contour_territory(ax, terr, "white")
    for i, c in enumerate(cams):
        ax.plot(c.center[0] / 100, c.center[1] / 100, "k^", ms=8, mec="w")
    ax.set_title("Тепловая карта присутствия (вид сверху)")
    fig.colorbar(im, ax=ax, shrink=0.5, label="относительная плотность")
    ax.set_xlabel("X, м"); ax.set_ylabel("Y, м")
    fig.tight_layout(); fig.savefig(OUT / "heatmap.png", dpi=110); plt.close(fig)

    # число людей во времени
    t = np.arange(len(frames)) / fps
    n_all = [sum(p["in_terr"] for p in fr) for fr in frames]
    n_2 = [sum(p["in_terr"] and p["ncams"] >= 2 for p in fr) for fr in frames]
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(t, n_all, label="найдено (любая поддержка)", color="#2f6df6", lw=1)
    ax.plot(t, n_2, label="найдено (минимум 2 камеры)", color="#1f9d55", lw=1)
    from calib import position_id_to_xy  # noqa: F401
    from fuse import cell_lookup
    gt = data["gt"]
    if gt:
        ax.plot([k / fps for k in gt], [int(cell_lookup(terr, g).sum()) for g in gt.values()], "o", ms=3,
                color="#d93a3a", label="разметка датасета")
    for e in data["events"]:
        ax.axvline(e["t"], color="#1f9d55" if e["kind"] == "enter" else "#f59e0b", alpha=0.12)
    ax.set_xlabel("секунды"); ax.set_ylabel("людей в территории"); ax.legend(); ax.grid(alpha=0.3)
    ax.set_title("Людей в территории (зелёные/оранжевые линии — заходы/выходы)")
    fig.tight_layout(); fig.savefig(OUT / "counts.png", dpi=110); plt.close(fig)


def topdown_frame(data: dict, cams, k: int, trails: dict, heat: np.ndarray) -> np.ndarray:
    S = 0.4  # пикселей на сантиметр / 2.5  → 12 м × 36 м = 480 × 1440; уменьшаем вдвое
    w, h = int((X_MAX - X_MIN) * 0.2), int((Y_MAX - Y_MIN) * 0.2)
    img = np.full((h, w, 3), 30, np.uint8)
    ext = cv2.resize(data["extended"].astype(np.uint8) * 45, (w, h), interpolation=cv2.INTER_NEAREST)
    img[:, :, 1] = np.maximum(img[:, :, 1], ext)
    terr = cv2.resize(data["territory"].astype(np.uint8) * 60, (w, h), interpolation=cv2.INTER_NEAREST)
    img[:, :, 0] = np.maximum(img[:, :, 0], terr)
    for c in territory_contours(data["territory"]):
        pts = np.c_[(c[:, 0] - X_MIN) * 0.2, (c[:, 1] - Y_MIN) * 0.2].astype(np.int32)
        cv2.polylines(img, [pts], True, (255, 220, 0), 1, cv2.LINE_AA)
    for cam in cams:
        p = ((cam.center[:2] - [X_MIN, Y_MIN]) * 0.2).astype(int)
        cv2.drawMarker(img, tuple(int(v) for v in p), (255, 255, 255), cv2.MARKER_TRIANGLE_UP, 10, 2)
    for p in data["frames"][k]:
        pos = (int((p["x"] - X_MIN) * 0.2), int((p["y"] - Y_MIN) * 0.2))
        if p["track"] is not None:
            trails.setdefault(p["track"], []).append(pos)
            tr = trails[p["track"]][-25:]
            if len(tr) > 1:
                cv2.polylines(img, [np.array(tr)], False, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.circle(img, pos, 4, GREEN if p["in_terr"] else ORANGE, -1, cv2.LINE_AA)
    n = sum(p["in_terr"] for p in data["frames"][k])
    cv2.putText(img, f"v territorii: {n}", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1, cv2.LINE_AA)
    return img


def encode_h264(src: str, dst: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", src, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23", dst],
                   check=True)


def videos(data: dict, cams, start: float, seconds: float) -> None:
    fps = data["fps"]
    k0, k1 = int(start * fps), min(int((start + seconds) * fps), len(data["frames"]))
    contours = territory_contours(data["territory"])
    caps = [cv2.VideoCapture(str(DATASET / f"cam{i + 1}.mp4")) for i in range(7)]
    maps = [undistort_maps(i) for i in range(7)]
    offsets = load_offsets()
    dets = {ci: np.load(OUT / f"det{data['args']['tag']}_cam{ci + 1}.npy") for ci in range(7)}
    by_k = {ci: {} for ci in range(7)}
    for ci, a in dets.items():
        for j, row in enumerate(a):
            by_k[ci].setdefault(int(row[0]), []).append(row)
    tw, th = 480, 270
    mosaic = cv2.VideoWriter(str(OUT / "_mosaic.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (tw * 4, th * 2))
    top_h = int((Y_MAX - Y_MIN) * 0.2)
    top = cv2.VideoWriter(str(OUT / "_topdown.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (int((X_MAX - X_MIN) * 0.2), top_h))
    trails: dict = {}
    sheet_ks = {k0, k0 + (k1 - k0) // 2}
    pos = [0] * 7
    for k in range(k0, k1):
        tiles = []
        for ci, cap in enumerate(caps):
            target = frame_index(k / fps, ci, offsets)
            if k == k0:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target)
                pos[ci] = target
            while pos[ci] < target:
                cap.grab(); pos[ci] += 1
            ok, frame = cap.read(); pos[ci] += 1
            if not ok:
                frame = np.zeros((IMG_H, IMG_W, 3), np.uint8)
            frame = cv2.remap(frame, maps[ci][0], maps[ci][1], cv2.INTER_LINEAR)
            small = cv2.resize(frame, (tw * 2, th * 2))  # 960×540 для рисования
            draw_territory(small, cams[ci], contours, 0.5)
            member = {}
            for p in data["frames"][k]:
                for cj, j in p["members"]:
                    if cj == ci:
                        member[j] = p
            for j, row in enumerate(by_k[ci].get(k, [])):
                x1, y1, x2, y2 = (row[1:5] * 0.5).astype(int)
                p = member.get(j)
                if p is None:
                    cv2.rectangle(small, (x1, y1), (x2, y2), GRAY, 1)
                    continue
                color = GREEN if p["in_terr"] else ORANGE
                cv2.rectangle(small, (x1, y1), (x2, y2), color, 2)
                if p["track"] is not None and p["in_terr"]:
                    cv2.putText(small, str(p["track"]), (x1, max(12, y1 - 3)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
            n = sum(q["in_terr"] for q in data["frames"][k])
            cv2.rectangle(small, (0, 0), (330, 30), (0, 0, 0), -1)
            cv2.putText(small, f"C{ci + 1}  v territorii: {n}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2, cv2.LINE_AA)
            if k in sheet_ks:
                cv2.imwrite(str(OUT / f"sheet_cam{ci + 1}_t{k / fps:.0f}s.jpg"), small, [cv2.IMWRITE_JPEG_QUALITY, 85])
            tiles.append(cv2.resize(small, (tw, th)))
        tiles.append(np.zeros((th, tw, 3), np.uint8))
        mosaic.write(np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])]))
        top.write(topdown_frame(data, cams, k, trails, None))
        if k in sheet_ks:
            cv2.imwrite(str(OUT / f"sheet_topdown_t{k / fps:.0f}s.png"), topdown_frame(data, cams, k, {}, None))
    mosaic.release(); top.release()
    encode_h264(str(OUT / "_mosaic.mp4"), str(OUT / "cams_mosaic.mp4"))
    encode_h264(str(OUT / "_topdown.mp4"), str(OUT / "topdown.mp4"))
    (OUT / "_mosaic.mp4").unlink(); (OUT / "_topdown.mp4").unlink()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-video", action="store_true")
    args = ap.parse_args()
    with open(OUT / f"fused{args.tag}.pkl", "rb") as fh:
        data = pickle.load(fh)
    data["args"]["tag"] = args.tag
    cams = load_cameras()
    plots(data, cams)
    print("графики готовы", flush=True)
    if not args.no_video:
        videos(data, cams, args.start, args.seconds)
        print("видео готовы", flush=True)


if __name__ == "__main__":
    main()
