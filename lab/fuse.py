"""Этап 2: территория, склейка людей между камерами на плоскости земли, трекинг, заходы/выходы,
тепловая карта и сверка с разметкой датасета.

  python fuse.py --seconds 200 --fps 10
Входит: data/output/det_cam*.npy. Выходит: data/output/fused.pkl, summary.json, графики.
"""
import argparse
import glob
import json
import pickle

import cv2
import numpy as np
from scipy.ndimage import binary_opening, distance_transform_edt, label
from scipy.optimize import linear_sum_assignment

from calib import (DATASET, IMG_H, IMG_W, OUT, X_MAX, X_MIN, Y_MAX, Y_MIN, load_cameras,
                   position_id_to_xy)

CELL = 10.0  # см, размер ячейки масок территории
NX, NY = int((X_MAX - X_MIN) / CELL), int((Y_MAX - Y_MIN) / CELL)
PERSON_H = 170.0
MIN_PX_HEIGHT = 45  # человек меньше этого в кадре считается «не виден надёжно»


def cell_centers() -> np.ndarray:
    xs = X_MIN + (np.arange(NX) + 0.5) * CELL
    ys = Y_MIN + (np.arange(NY) + 0.5) * CELL
    gx, gy = np.meshgrid(xs, ys)
    return np.stack([gx, gy], axis=-1).reshape(-1, 2)


def visibility(cams) -> np.ndarray:
    """Сколько камер надёжно видит человека, стоящего в каждой ячейке: (NY, NX)."""
    pts = cell_centers()
    feet = np.c_[pts, np.zeros(len(pts))]
    heads = np.c_[pts, np.full(len(pts), PERSON_H)]
    count = np.zeros(len(pts), dtype=int)
    for cam in cams:
        fuv, fz = cam.project(feet)
        huv, _ = cam.project(heads)
        ok = (
            (fz > 0)
            & (fuv[:, 0] > 5) & (fuv[:, 0] < IMG_W - 5)
            & (fuv[:, 1] > 5) & (fuv[:, 1] < IMG_H - 5)
            & (huv[:, 1] > -30)
            & ((fuv[:, 1] - huv[:, 1]) >= MIN_PX_HEIGHT)
        )
        count += ok
    return count.reshape(NY, NX)


def build_territory(vis: np.ndarray, min_cams: int) -> tuple[np.ndarray, np.ndarray]:
    """territory: ячейки, видимые >= min_cams камерами (крупнейшая связная область, без шума);
    extended: видимые хотя бы одной камерой, нужна для отслеживания пересечения границы."""
    mask = binary_opening(vis >= min_cams, iterations=2)
    lab, n = label(mask)
    if n:
        sizes = np.bincount(lab.ravel())[1:]
        mask = lab == (1 + int(np.argmax(sizes)))
    return mask, vis >= 1


def vis_at(vis: np.ndarray, xy: np.ndarray) -> np.ndarray:
    ix = np.clip(np.floor((xy[:, 0] - X_MIN) / CELL).astype(int), 0, NX - 1)
    iy = np.clip(np.floor((xy[:, 1] - Y_MIN) / CELL).astype(int), 0, NY - 1)
    return vis[iy, ix]


def cell_lookup(mask: np.ndarray, xy: np.ndarray) -> np.ndarray:
    ix = np.floor((xy[:, 0] - X_MIN) / CELL).astype(int)
    iy = np.floor((xy[:, 1] - Y_MIN) / CELL).astype(int)
    ok = (ix >= 0) & (ix < NX) & (iy >= 0) & (iy < NY)
    out = np.zeros(len(xy), dtype=bool)
    out[ok] = mask[iy[ok], ix[ok]]
    return out


def fuse_frame(dets: dict[int, np.ndarray], cams, extended: np.ndarray, gate_k: float, min_conf: float,
               sigma_near: float = 30.0, sigma_slope: float = 0.055):
    """dets[cam] = (N,5) [x1,y1,x2,y2,conf]. Возвращает кластеры людей на земле.

    Ошибка позиции по одной камере растёт с расстоянием (вблизи ~30 см, на 20 м ~1 м), поэтому у каждой
    детекции своя сигма; склеиваем, если расстояние < gate_k · sqrt(σ1² + σ2²), позицию усредняем с весом 1/σ²."""
    items = []  # (sigma, cam, det_idx, X, Y, conf)
    for ci, d in dets.items():
        if len(d) == 0:
            continue
        keep = (d[:, 4] >= min_conf) & (d[:, 3] < IMG_H - 3)  # ноги обрезаны краем кадра — позиция неверна
        idx = np.where(keep)[0]
        if len(idx) == 0:
            continue
        foot = np.c_[(d[idx, 0] + d[idx, 2]) / 2, d[idx, 3]]
        xy, ok = cams[ci].to_ground(foot)
        ok &= cell_lookup(extended, xy)
        dist = np.linalg.norm(xy - cams[ci].center[:2], axis=1)
        for i, (j, good) in enumerate(zip(idx, ok)):
            if good:
                sigma = max(sigma_near, sigma_slope * dist[i])
                items.append((sigma, ci, int(j), float(xy[i, 0]), float(xy[i, 1]), float(d[j, 4])))
    items.sort(key=lambda it: it[0])  # сначала самые точные (ближние) — они задают «якоря»

    clusters: list[dict] = []
    for sigma, ci, j, x, y, conf in items:
        w = 1.0 / sigma**2
        best, best_score = None, 1.0
        for cl in clusters:
            if ci in cl["cams"]:
                continue
            gate = gate_k * np.sqrt(sigma**2 + 1.0 / cl["w"])
            score = np.hypot(cl["x"] - x, cl["y"] - y) / gate
            if score < best_score:
                best, best_score = cl, score
        if best is None:
            clusters.append({"x": x, "y": y, "w": w, "cams": {ci}, "members": [(ci, j)], "conf": conf})
        else:
            tw = best["w"] + w
            best["x"] = (best["x"] * best["w"] + x * w) / tw
            best["y"] = (best["y"] * best["w"] + y * w) / tw
            best["w"] = tw
            best["cams"].add(ci)
            best["members"].append((ci, j))
            best["conf"] = max(best["conf"], conf)
    return clusters


class Tracker:
    """Трекер на плоскости земли: венгерский алгоритм по расстоянию, потеря до max_miss кадров."""

    def __init__(self, gate: float = 100.0, max_miss: int = 10, confirm: int = 3):
        self.gate, self.max_miss, self.confirm = gate, max_miss, confirm
        self.tracks: list[dict] = []
        self.next_id = 1

    def update(self, pts: np.ndarray) -> list[int | None]:
        """pts (N,2) -> id трека для каждой точки (None, если трек ещё не подтверждён)."""
        assigned: list[int | None] = [None] * len(pts)
        match_t, match_d = {}, {}
        if self.tracks and len(pts):
            pred = np.array([t["pos"] + t["vel"] for t in self.tracks])
            cost = np.linalg.norm(pred[:, None, :] - pts[None, :, :], axis=2)
            cost_g = np.where(cost > self.gate, 1e6, cost)
            for ti, di in zip(*linear_sum_assignment(cost_g)):
                if cost[ti, di] <= self.gate:
                    match_t[ti], match_d[di] = di, ti
        for ti, t in enumerate(self.tracks):
            if ti in match_t:
                p = pts[match_t[ti]]
                t["vel"] = 0.6 * t["vel"] + 0.4 * (p - t["pos"])
                t["pos"], t["hits"], t["miss"] = p, t["hits"] + 1, 0
            else:
                t["miss"] += 1
                t["pos"] = t["pos"] + t["vel"] * 0.5
        for di in range(len(pts)):
            if di not in match_d:
                self.tracks.append({"id": self.next_id, "pos": pts[di].copy(), "vel": np.zeros(2),
                                    "hits": 1, "miss": 0})
                self.next_id += 1
                match_d[di] = len(self.tracks) - 1
        for di, ti in match_d.items():
            if self.tracks[ti]["hits"] >= self.confirm:
                assigned[di] = self.tracks[ti]["id"]
        self.tracks = [t for t in self.tracks if t["miss"] <= self.max_miss]
        return assigned


def border_distance(territory: np.ndarray) -> np.ndarray:
    """Для ячеек территории — расстояние (см) до её границы; снаружи 0."""
    padded = np.pad(territory, 1)
    return distance_transform_edt(padded)[1:-1, 1:-1] * CELL


def count_events(histories: dict, border: np.ndarray, fps: float, n_frames: int, hysteresis: int,
                 border_cm: float) -> list[dict]:
    """Заходы/выходы по истории трека.

    • пересечение границы, подтверждённое `hysteresis` наблюдениями подряд;
    • трек, появившийся внутри у самой границы, пришёл из невидимой зоны — это заход;
      пропавший внутри у границы — выход. Появления и пропажи в глубине территории — это
      перекрытия и сбои трекинга, их не считаем."""
    events = []
    for tid, h in histories.items():
        h = sorted(h)
        def near(x, y):
            return float(border_at(border, np.array([[x, y]]))[0]) <= border_cm
        k0, x0, y0, in0 = h[0]
        if in0 and k0 > hysteresis and near(x0, y0):
            events.append({"k": k0, "t": k0 / fps, "track": tid, "kind": "enter", "x": x0, "y": y0, "how": "appeared"})
        state, streak = in0, 0
        for k, x, y, inside in h[1:]:
            if inside == state:
                streak = 0
                continue
            streak += 1
            if streak >= hysteresis:
                events.append({"k": k, "t": k / fps, "track": tid, "kind": "enter" if inside else "exit", "x": x, "y": y,
                               "how": "crossed"})
                state, streak = inside, 0
        k1, x1, y1, in1 = h[-1]
        if state and in1 and k1 < n_frames - 1 - hysteresis and near(x1, y1):
            events.append({"k": k1, "t": k1 / fps, "track": tid, "kind": "exit", "x": x1, "y": y1, "how": "vanished"})
    return sorted(events, key=lambda e: e["k"])


def stitch(histories: dict, fps: float, **kw) -> dict:
    """Сшивка оборванных треков: продолжение, начавшееся вскоре и рядом с концом другого трека,
    считаем тем же человеком (жадно, по возрастанию «стоимости»)."""
    roots = stitch_map(histories, fps, **kw)
    merged: dict[int, list] = {}
    for tid, h in histories.items():
        merged.setdefault(roots[tid], []).extend(h)
    return {tid: sorted(h) for tid, h in merged.items()}


def stitch_map(histories: dict, fps: float, max_gap_s: float = 3.0, base_cm: float = 120.0,
               speed_cm_s: float = 150.0) -> dict[int, int]:
    """id трека -> id первого трека в сшитой цепочке."""
    tracks = {tid: sorted(h) for tid, h in histories.items()}
    candidates = []
    ends = {tid: h[-1] for tid, h in tracks.items()}
    starts = {tid: h[0] for tid, h in tracks.items()}
    for a, (ka, xa, ya, _) in ends.items():
        for b, (kb, xb, yb, _) in starts.items():
            if a == b or not (0 < kb - ka <= max_gap_s * fps):
                continue
            gap_s = (kb - ka) / fps
            dist = np.hypot(xb - xa, yb - ya)
            if dist <= base_cm + speed_cm_s * gap_s:
                candidates.append((dist / (base_cm + speed_cm_s * gap_s) + gap_s / max_gap_s, a, b))
    parent: dict[int, int] = {}
    used_end, used_start = set(), set()
    for _, a, b in sorted(candidates):
        if a in used_end or b in used_start:
            continue
        used_end.add(a)
        used_start.add(b)
        parent[b] = a

    def root(t: int) -> int:
        while t in parent:
            t = parent[t]
        return t

    return {tid: root(tid) for tid in tracks}


def border_at(border: np.ndarray, xy: np.ndarray) -> np.ndarray:
    ix = np.clip(np.floor((xy[:, 0] - X_MIN) / CELL).astype(int), 0, NX - 1)
    iy = np.clip(np.floor((xy[:, 1] - Y_MIN) / CELL).astype(int), 0, NY - 1)
    return border[iy, ix]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=200)
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--gate-k", type=float, default=2.0, help="порог склейки в сигмах ошибки позиции")
    ap.add_argument("--support", default="auto", choices=["1", "2", "auto"],
                    help="сколько камер должны подтвердить человека; auto: 2 там, где точку видят 3+ камеры, иначе 1")
    ap.add_argument("--min-conf", type=float, default=0.3)
    ap.add_argument("--min-cams", type=int, default=3, help="камер, видящих территорию")
    ap.add_argument("--sigma-near", type=float, default=30.0, help="ошибка позиции вблизи камеры, см")
    ap.add_argument("--sigma-slope", type=float, default=0.055, help="рост ошибки на см расстояния")
    ap.add_argument("--border-cm", type=float, default=150.0,
                    help="появление/исчезновение трека ближе этого к границе считается заходом/выходом")
    ap.add_argument("--stitch", type=int, default=1, help="сшивать оборванные треки (1/0)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    cams = load_cameras()
    vis = visibility(cams)
    territory, extended = build_territory(vis, args.min_cams)
    print(f"территория: {territory.sum() * CELL * CELL / 1e4:.0f} м², видимая хотя бы одной камерой: "
          f"{extended.sum() * CELL * CELL / 1e4:.0f} м²", flush=True)

    dets = {}
    for ci in range(7):
        a = np.load(OUT / f"det{args.tag}_cam{ci + 1}.npy")
        dets[ci] = a
    n = int(args.seconds * args.fps)

    by_frame = {ci: [[] for _ in range(n)] for ci in range(7)}
    for ci, a in dets.items():
        for row in a:
            k = int(row[0])
            if k < n:
                by_frame[ci][k].append(row[1:6])

    tracker = Tracker()
    frames = []  # на кадр: список людей {x,y,ncams,conf,in_terr,track,members}
    histories: dict[int, list] = {}  # трек -> [(k, x, y, inside)]
    for k in range(n):
        d = {ci: np.array(by_frame[ci][k]).reshape(-1, 5) for ci in range(7)}
        cl = fuse_frame(d, cams, extended, args.gate_k, args.min_conf, args.sigma_near, args.sigma_slope)
        if cl:
            xy = np.array([[c["x"], c["y"]] for c in cl])
            seen = vis_at(vis, xy)
            need = np.ones(len(cl), dtype=int) if args.support == "1" else (
                np.full(len(cl), 2) if args.support == "2" else np.where(seen >= 3, 2, 1))
            cl = [c for c, nd in zip(cl, need) if len(c["cams"]) >= nd]
        pts = np.array([[c["x"], c["y"]] for c in cl]).reshape(-1, 2)
        ids = tracker.update(pts)
        in_terr = cell_lookup(territory, pts) if len(pts) else np.zeros(0, dtype=bool)
        people = []
        for c, tid, inside in zip(cl, ids, in_terr):
            people.append({"x": c["x"], "y": c["y"], "ncams": len(c["cams"]), "conf": c["conf"],
                           "in_terr": bool(inside), "track": tid, "members": c["members"]})
            if tid is not None:
                histories.setdefault(tid, []).append((k, c["x"], c["y"], bool(inside)))
        frames.append(people)
        if k % 500 == 0:
            print(f"слияние: кадр {k}/{n}", flush=True)

    border = border_distance(territory)
    stitched = stitch(histories, args.fps) if args.stitch else histories
    print(f"треков: {len(histories)}, после сшивки: {len(stitched)}", flush=True)
    events = count_events(stitched, border, args.fps, n, hysteresis=3, border_cm=args.border_cm)

    # ---- сверка с разметкой (только первые кадры, где она есть) ---------------------------
    gt_frames = {}
    for f in sorted(glob.glob(str(DATASET / "annotations_positions" / "*.json"))):
        # имя файла — номер кадра при 10 к/с; берём только моменты, совпадающие с нашей выборкой
        t = int(f.replace("\\", "/").split("/")[-1].split(".")[0]) / 10
        k = round(t * args.fps)
        if abs(t * args.fps - k) < 1e-6 and k < n:
            gt_frames[k] = position_id_to_xy(np.array([p["positionID"] for p in json.load(open(f))]))

    def evaluate(min_support: int, region: np.ndarray | None, thr: float = 75.0) -> dict:
        tp = fp = fn = 0
        errs, abs_cnt = [], []
        for k, gt in gt_frames.items():
            pr = np.array([[p["x"], p["y"]] for p in frames[k] if p["ncams"] >= min_support]).reshape(-1, 2)
            g = gt
            if region is not None:
                g = gt[cell_lookup(region, gt)] if len(gt) else gt
                pr = pr[cell_lookup(region, pr)] if len(pr) else pr
            if len(g) and len(pr):
                cost = np.linalg.norm(g[:, None] - pr[None], axis=2)
                r, c = linear_sum_assignment(cost)
                ok = cost[r, c] <= thr
                tp += int(ok.sum())
                errs += list(cost[r, c][ok])
            else:
                ok = np.zeros(0, dtype=bool)
            matched = int(ok.sum())
            fp += len(pr) - matched
            fn += len(g) - matched
            abs_cnt.append(abs(len(pr) - len(g)))
        p, r_ = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        return {"precision": round(p, 3), "recall": round(r_, 3), "f1": round(2 * p * r_ / max(p + r_, 1e-9), 3),
                "count_mae": round(float(np.mean(abs_cnt)), 2), "pos_err_cm": round(float(np.median(errs)), 1) if errs else None,
                "frames": len(gt_frames)}

    summary = {
        "args": vars(args),
        "territory_m2": round(float(territory.sum() * CELL * CELL / 1e4), 1),
        "visible_m2": round(float(extended.sum() * CELL * CELL / 1e4), 1),
        "events": {"enter": sum(e["kind"] == "enter" for e in events), "exit": sum(e["kind"] == "exit" for e in events)},
        "avg_people_in_territory": round(float(np.mean([sum(p["in_terr"] for p in fr) for fr in frames])), 1),
    }
    if gt_frames:
        summary["vs_dataset_labels"] = {"territory": evaluate(1, territory), "whole_grid": evaluate(1, extended)}
        gt_hist: dict[int, list] = {}
        for f in sorted(glob.glob(str(DATASET / "annotations_positions" / "*.json"))):
            kk = int(f.replace("\\", "/").split("/")[-1].split(".")[0]) // 5  # индекс при 2 к/с
            if kk / 2 >= args.seconds:
                continue
            for p in json.load(open(f)):
                x, y = position_id_to_xy(p["positionID"])
                gt_hist.setdefault(p["personID"], []).append((kk, x, y, bool(cell_lookup(territory, np.array([[x, y]]))[0])))
        n_gt = int(args.seconds * 2)
        gt_events = count_events(gt_hist, border, 2.0, n_gt, hysteresis=1, border_cm=args.border_cm)
        summary["events_dataset_labels"] = {"enter": sum(e["kind"] == "enter" for e in gt_events),
                                            "exit": sum(e["kind"] == "exit" for e in gt_events)}
        # сверка по каждому событию: тот же тип, не дальше 2 с и 2 м
        ours = [e for e in events if e["t"] < args.seconds]
        used, hits = set(), 0
        for e in sorted(ours, key=lambda e: e["t"]):
            best = None
            for i, g in enumerate(gt_events):
                if i in used or g["kind"] != e["kind"] or abs(g["t"] - e["t"]) > 2.0:
                    continue
                dist = np.hypot(g["x"] - e["x"], g["y"] - e["y"])
                if dist <= 200 and (best is None or dist < best[0]):
                    best = (dist, i)
            if best:
                used.add(best[1])
                hits += 1
        summary["events_match"] = {"matched": hits, "precision": round(hits / max(len(ours), 1), 3),
                                   "recall": round(hits / max(len(gt_events), 1), 3)}
        summary["avg_gt_in_territory"] = round(float(np.mean([cell_lookup(territory, g).sum() for g in gt_frames.values()])), 1)
    (OUT / f"summary{args.tag}.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    with open(OUT / f"fused{args.tag}.pkl", "wb") as fh:
        pickle.dump({"frames": frames, "events": events, "territory": territory, "extended": extended, "vis": vis,
                     "gt": gt_frames, "fps": args.fps, "args": vars(args)}, fh)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
