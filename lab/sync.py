"""Синхронизация камер: для каждой камеры ищем постоянный сдвиг (в кадрах) видео относительно общей
временной шкалы. Шкала задана кадрами разметки датасета, поэтому сдвиги одновременно синхронизируют
камеры между собой и привязывают видео к разметке.

  python sync.py           -> data/output/sync.json
"""
import json

import cv2
import numpy as np

from calib import DATASET, OUT, TIMELINE_FPS, undistort_maps

PROBE_TIMES = (40.0, 100.0, 160.0)  # секунды
SEARCH = 60  # ±кадров вокруг номинала


def small(img: np.ndarray) -> np.ndarray:
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (320, 180)).astype(np.float32)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    offsets, details = [], {}
    for ci in range(7):
        m1, m2 = undistort_maps(ci)
        cap = cv2.VideoCapture(str(DATASET / f"cam{ci + 1}.mp4"))
        found = []
        for t in PROBE_TIMES:
            ref = small(cv2.imread(str(DATASET / "Image_subsets" / f"C{ci + 1}" / f"{int(t * 10):08d}.png")))
            nominal = round(t * TIMELINE_FPS)
            cap.set(cv2.CAP_PROP_POS_FRAMES, nominal - SEARCH)
            errs = []
            for _ in range(2 * SEARCH + 1):
                ok, fr = cap.read()
                if not ok:
                    break
                errs.append(np.abs(small(cv2.remap(fr, m1, m2, cv2.INTER_LINEAR)) - ref).mean())
            best = int(np.argmin(errs))
            found.append((best - SEARCH, float(errs[best])))
        cap.release()
        off = int(np.median([f[0] for f in found]))
        offsets.append(off)
        details[f"C{ci + 1}"] = [{"t": t, "offset": f[0], "err": round(f[1], 2)} for t, f in zip(PROBE_TIMES, found)]
        print(f"C{ci + 1}: сдвиг {off:+d} кадров ({off / TIMELINE_FPS:+.3f} с), замеры {[f[0] for f in found]}, "
              f"ошибка совпадения {[round(f[1], 1) for f in found]}", flush=True)
    (OUT / "sync.json").write_text(json.dumps({"offsets_frames": offsets, "details": details}, indent=2))


if __name__ == "__main__":
    main()
