"""Этап 1: YOLO по 7 видео. Кадры берутся с частотой --fps по времени видео, детекции кешируются.

  python detect.py --seconds 200 --fps 10
Результат: data/output/det_cam{1..7}.npy, строки [k, x1, y1, x2, y2, conf], k — номер выборки (k/fps секунд).
"""
import argparse
import time

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from calib import DATASET, OUT, frame_index, load_offsets, undistort_maps


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="yolo11m.pt")
    ap.add_argument("--imgsz", type=int, default=1280)
    ap.add_argument("--seconds", type=float, default=200)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--conf", type=float, default=0.2)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--cams", default="1,2,3,4,5,6,7")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)
    device = 0 if torch.cuda.is_available() else "cpu"
    print("device:", torch.cuda.get_device_name(0) if device == 0 else "CPU", flush=True)
    n_samples = int(args.seconds * args.fps)
    offsets = load_offsets()
    print("сдвиги синхронизации:", offsets, flush=True)

    for cam in [int(c) for c in args.cams.split(",")]:
        cap = cv2.VideoCapture(str(DATASET / f"cam{cam}.mp4"))
        m1, m2 = undistort_maps(cam - 1)
        targets = [frame_index(k / args.fps, cam - 1, offsets) for k in range(n_samples)]
        rows: list[list[float]] = []
        batch, batch_k = [], []
        pos, ti, t0 = 0, 0, time.time()

        def flush() -> None:
            if not batch:
                return
            res = model.predict(batch, imgsz=args.imgsz, classes=[0], conf=args.conf, half=device == 0,
                                device=device, verbose=False)
            for k, r in zip(batch_k, res):
                for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                    rows.append([k, x1, y1, x2, y2, c])
            batch.clear()
            batch_k.clear()

        while ti < n_samples:
            if not cap.grab():
                break
            if pos == targets[ti]:
                ok, frame = cap.retrieve()
                if ok:
                    batch.append(cv2.remap(frame, m1, m2, cv2.INTER_LINEAR))  # убираем дисторсию объектива
                    batch_k.append(ti)
                    if len(batch) == args.batch:
                        flush()
                ti += 1
                if ti % 200 == 0:
                    print(f"cam{cam}: {ti}/{n_samples} кадров, {ti / (time.time() - t0):.1f} кадр/с", flush=True)
            pos += 1
        flush()
        cap.release()
        arr = np.array(rows, dtype=np.float32).reshape(-1, 6)
        np.save(OUT / f"det{args.tag}_cam{cam}.npy", arr)
        print(f"cam{cam}: готово, {len(arr)} детекций, {time.time() - t0:.0f} с", flush=True)


if __name__ == "__main__":
    main()
