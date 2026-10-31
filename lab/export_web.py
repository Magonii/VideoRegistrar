"""Экспорт для веб-страницы «Мультикамера»: синхронные видео без дисторсии + данные для наложения.

  python export_web.py --seconds 200
Выход: data/output/web/cam{1..7}.mp4 и data/output/web/lab.json
Все видео начинаются в момент t=0 общей шкалы, поэтому в браузере их достаточно держать на одном currentTime.
"""
import argparse
import json
import pickle
import subprocess
from multiprocessing import Pool

import cv2
import numpy as np

from calib import (DATASET, IMG_H, IMG_W, OUT, X_MAX, X_MIN, Y_MAX, Y_MIN, frame_index, load_cameras, load_offsets,
                   undistort_maps)
from fuse import stitch_map
from render import territory_contours

WEB = OUT / "web"
VW, VH, VFPS = 960, 540, 25


def encode_camera(job: tuple[int, float, list[int]]) -> str:
    ci, seconds, offsets = job
    m1, m2 = undistort_maps(ci)
    cap = cv2.VideoCapture(str(DATASET / f"cam{ci + 1}.mp4"))
    out = WEB / f"cam{ci + 1}.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{VW}x{VH}", "-r", str(VFPS),
         "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-g", str(VFPS), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE,
    )
    pos = 0
    for m in range(int(seconds * VFPS)):
        target = frame_index(m / VFPS, ci, offsets)
        while pos < target:
            cap.grab()
            pos += 1
        ok, frame = cap.read()
        pos += 1
        if not ok:
            frame = np.zeros((IMG_H, IMG_W, 3), np.uint8)
        frame = cv2.resize(cv2.remap(frame, m1, m2, cv2.INTER_LINEAR), (VW, VH), interpolation=cv2.INTER_AREA)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()
    cap.release()
    return out.name


MOSAIC_COLS = 4


def mosaic_layout() -> dict:
    tiles = [[(i % MOSAIC_COLS) * VW, (i // MOSAIC_COLS) * VH] for i in range(7)]
    return {"file": "mosaic.mp4", "tile_w": VW, "tile_h": VH, "width": VW * MOSAIC_COLS, "height": VH * 2, "tiles": tiles}


def build_mosaic() -> None:
    """Все 7 камер в одном видео 4×2. Браузер держит не больше 6 соединений к одному серверу, поэтому
    7 отдельных видео не грузятся одновременно; одно общее видео к тому же синхронно по построению."""
    inputs = []
    for ci in range(7):
        inputs += ["-i", str(WEB / f"cam{ci + 1}.mp4")]
    inputs += ["-f", "lavfi", "-i", f"color=c=black:s={VW}x{VH}:r={VFPS}"]
    layout = "|".join(f"{(i % MOSAIC_COLS) * VW}_{(i // MOSAIC_COLS) * VH}" for i in range(8))
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", f"xstack=inputs=8:layout={layout}:shortest=1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-g", str(VFPS), "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(WEB / "mosaic.mp4")],
        check=True,
    )


def camera_territory(cam, contours) -> list[list[list[float]]]:
    """Граница территории в кадре камеры: ломаные в долях кадра (0..1), только видимые участки."""
    runs = []
    for c in contours:
        dense = np.concatenate([np.linspace(c[i], c[(i + 1) % len(c)], 8, endpoint=False) for i in range(len(c))])
        dense = np.vstack([dense, dense[:1]])
        uv, z = cam.project(np.c_[dense, np.zeros(len(dense))])
        run: list = []
        for (u, v), zz in zip(uv, z):
            if zz > 0 and -2 * IMG_W < u < 3 * IMG_W and -2 * IMG_H < v < 3 * IMG_H:
                run.append([round(u / IMG_W, 4), round(v / IMG_H, 4)])
            else:
                if len(run) > 1:
                    runs.append(run)
                run = []
        if len(run) > 1:
            runs.append(run)
    return runs


def build_json(seconds: float, offsets: list[int]) -> dict:
    with open(OUT / "fused.pkl", "rb") as fh:
        data = pickle.load(fh)
    fps = data["fps"]
    frames = data["frames"][: int(seconds * fps)]
    cams = load_cameras()

    histories: dict[int, list] = {}
    for k, people in enumerate(frames):
        for p in people:
            if p["track"] is not None:
                histories.setdefault(p["track"], []).append((k, p["x"], p["y"], p["in_terr"]))
    roots = stitch_map(histories, fps)  # те же номера, что у событий заходов/выходов

    boxes: list[list] = [[] for _ in range(7)]
    for ci in range(7):
        det = np.load(OUT / f"det_cam{ci + 1}.npy")
        by_k: dict[int, list] = {}
        for row in det:
            by_k.setdefault(int(row[0]), []).append(row)
        for k in range(len(frames)):
            owner = {}
            for p in frames[k]:
                for cj, j in p["members"]:
                    if cj == ci:
                        owner[j] = p
            items = []
            for j, row in enumerate(by_k.get(k, [])):
                p = owner.get(j)
                if p is None and row[5] < 0.3:
                    continue  # слабые неподтверждённые рамки не показываем
                track = roots.get(p["track"], p["track"]) if p is not None and p["track"] is not None else -1
                state = -1 if p is None else int(p["in_terr"])
                items.append([int(row[1]), int(row[2]), int(row[3]), int(row[4]), track, state])
            boxes[ci].append(items)

    contours = territory_contours(data["territory"])
    heat = np.load(OUT / "heat.npy")
    heat = (255 * heat / max(heat.max(), 1e-9)).astype(int)
    summary = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))

    return {
        "fps": fps,
        "duration": len(frames) / fps,
        "video": {"fps": VFPS, "width": VW, "height": VH},
        "mosaic": mosaic_layout(),
        "source": {"width": IMG_W, "height": IMG_H},
        "cameras": [
            {"id": ci + 1, "name": f"C{ci + 1}", "offset_frames": offsets[ci], "territory": camera_territory(cams[ci], contours),
             "position": [round(cams[ci].center[0] / 100, 2), round(cams[ci].center[1] / 100, 2)]}
            for ci in range(7)
        ],
        "ground": {
            "x_min": X_MIN / 100, "x_max": X_MAX / 100, "y_min": Y_MIN / 100, "y_max": Y_MAX / 100,
            "territory": [[[round(x / 100, 2), round(y / 100, 2)] for x, y in c] for c in contours],
            "territory_m2": summary["territory_m2"],
        },
        "frames": [
            {
                "n": sum(p["in_terr"] for p in fr),
                "p": [[roots.get(p["track"], p["track"]) if p["track"] is not None else -1,
                       round(p["x"] / 100, 2), round(p["y"] / 100, 2), int(p["in_terr"])] for p in fr],
            }
            for fr in frames
        ],
        "boxes": boxes,
        "events": [{"t": round(e["t"], 2), "kind": e["kind"], "track": e["track"], "x": round(e["x"] / 100, 2),
                    "y": round(e["y"] / 100, 2)} for e in data["events"] if e["t"] < seconds],
        "heat": {"rows": int(heat.shape[0]), "cols": int(heat.shape[1]), "values": heat.ravel().tolist()},
        "summary": summary,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--mosaic-only", action="store_true", help="камеры уже закодированы, собрать только мозаику")
    args = ap.parse_args()
    WEB.mkdir(parents=True, exist_ok=True)
    offsets = load_offsets()

    payload = build_json(args.seconds, offsets)
    (WEB / "lab.json").write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"lab.json: {(WEB / 'lab.json').stat().st_size / 1e6:.1f} МБ", flush=True)
    if args.json_only:
        return
    if not args.mosaic_only:
        with Pool(args.workers) as pool:
            for name in pool.imap_unordered(encode_camera, [(ci, args.seconds, offsets) for ci in range(7)]):
                print("готово:", name, flush=True)
    build_mosaic()
    print(f"готово: mosaic.mp4, {(WEB / 'mosaic.mp4').stat().st_size / 1e6:.0f} МБ", flush=True)


if __name__ == "__main__":
    main()
