"""Импорт результата эксперимента в основную систему.

Площадка становится этажом с планом в форме территории (как на виде сверху), 7 камер — камерами этого этажа,
а позиции людей — точками треков. По ним строит карту обычная страница «Тепловая карта».

  python import_to_app.py --backend http://localhost:8000 --start "2026-10-30 12:00"
Повторный запуск заменяет точки этого этажа, а не дублирует их.
"""
import argparse
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from calib import OUT

FLOOR_NAME = "Площадка WILDTRACK (7 камер)"
PX_PER_M = 40


def ground_bounds(lab: dict) -> dict:
    g = lab["ground"]
    xs = [g["x_min"], g["x_max"], *[c["position"][0] for c in lab["cameras"]]]
    ys = [g["y_min"], g["y_max"], *[c["position"][1] for c in lab["cameras"]]]
    return {"x0": min(xs) - 1, "x1": max(xs) + 1, "y0": min(ys) - 1, "y1": max(ys) + 1}


def to_plan(b: dict, x: float, y: float) -> tuple[float, float]:
    """Земля (м) -> доли плана. План горизонтальный: ось Y земли идёт вправо, X — вниз (как на виде сверху)."""
    return (y - b["y0"]) / (b["y1"] - b["y0"]), (x - b["x0"]) / (b["x1"] - b["x0"])


def plan_svg(lab: dict, b: dict) -> str:
    W = (b["y1"] - b["y0"]) * PX_PER_M
    H = (b["x1"] - b["x0"]) * PX_PER_M

    def P(x: float, y: float) -> str:
        u, v = to_plan(b, x, y)
        return f"{u * W:.1f},{v * H:.1f}"

    g = lab["ground"]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">',
        f'<rect width="{W:.0f}" height="{H:.0f}" fill="#f7f8fa"/>',
    ]
    (ax, ay), (bx, by) = [map(float, P(*p).split(",")) for p in ((g["x_min"], g["y_min"]), (g["x_max"], g["y_max"]))]
    parts.append(f'<rect x="{ax:.1f}" y="{ay:.1f}" width="{bx - ax:.1f}" height="{by - ay:.1f}" fill="#e9edf3" stroke="#c4ccd8"/>')
    # сетка 5 м
    y = (int(b["y0"] // 5) + 1) * 5
    while y < b["y1"]:
        u, _ = to_plan(b, 0, y)
        parts.append(f'<line x1="{u * W:.1f}" y1="0" x2="{u * W:.1f}" y2="{H:.0f}" stroke="#dde3eb" stroke-width="1"/>')
        y += 5
    x = (int(b["x0"] // 5) + 1) * 5
    while x < b["x1"]:
        _, v = to_plan(b, x, 0)
        parts.append(f'<line x1="0" y1="{v * H:.1f}" x2="{W:.0f}" y2="{v * H:.1f}" stroke="#dde3eb" stroke-width="1"/>')
        x += 5
    for poly in g["territory"]:
        pts = " ".join(P(px, py) for px, py in poly)
        parts.append(f'<polygon points="{pts}" fill="#38bdf8" fill-opacity="0.12" stroke="#0ea5e9" stroke-width="3"/>')
    for cam in lab["cameras"]:
        cx, cy = map(float, P(*cam["position"]).split(","))
        parts.append(f'<path d="M{cx:.1f},{cy - 11:.1f} L{cx - 9:.1f},{cy + 7:.1f} L{cx + 9:.1f},{cy + 7:.1f} Z" fill="#334155"/>')
        parts.append(f'<text x="{cx + 12:.1f}" y="{cy + 6:.1f}" font-family="sans-serif" font-size="16" font-weight="600" fill="#334155">{cam["name"]}</text>')
    parts.append(f'<text x="14" y="26" font-family="sans-serif" font-size="18" font-weight="600" fill="#2b3340">'
                 f'Площадка WILDTRACK · территория {g["territory_m2"]:.0f} м² (голубая)</text>')
    sx = 14
    parts.append(f'<line x1="{sx}" y1="{H - 16:.0f}" x2="{sx + 5 * PX_PER_M}" y2="{H - 16:.0f}" stroke="#2b3340" stroke-width="3"/>')
    parts.append(f'<text x="{sx}" y="{H - 24:.0f}" font-family="sans-serif" font-size="14" fill="#2b3340">5 м</text>')
    parts.append("</svg>")
    return "".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--start", default=None, help='начало записи по времени ТЦ, по умолчанию сегодня 12:00')
    ap.add_argument("--tz", default="Asia/Almaty")
    args = ap.parse_args()
    api = args.backend.rstrip("/") + "/api"

    lab = json.loads((OUT / "web" / "lab.json").read_text(encoding="utf-8"))
    b = ground_bounds(lab)
    tz = ZoneInfo(args.tz)
    start_local = (datetime.strptime(args.start, "%Y-%m-%d %H:%M") if args.start
                   else datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None))
    start_utc = start_local.replace(tzinfo=tz).astimezone(timezone.utc)

    floor = next((f for f in requests.get(f"{api}/floors").json() if f["name"] == FLOOR_NAME), None)
    if floor:
        cleared = requests.delete(f"{api}/floors/{floor['id']}/tracks").json()["deleted"]
        print(f"этаж уже есть (id {floor['id']}), удалено старых точек: {cleared}")
    else:
        floor = requests.post(f"{api}/floors", json={"name": FLOOR_NAME, "sort": 0, "capacity": None}).json()
        print(f"создан этаж id {floor['id']}")
    svg = plan_svg(lab, b)
    requests.post(f"{api}/floors/{floor['id']}/plan", files={"file": ("plan.svg", svg.encode("utf-8"), "image/svg+xml")}).raise_for_status()
    (OUT / "web" / "plan.svg").write_text(svg, encoding="utf-8")

    existing = {c["name"]: c for c in requests.get(f"{api}/cameras").json()}
    cam_ids = []
    for cam in lab["cameras"]:
        name = f"WILDTRACK {cam['name']}"
        c = existing.get(name) or requests.post(
            f"{api}/cameras",
            json={"name": name, "rtsp_url": f"data/TestDataset1/cam{cam['id']}.mp4", "floor_id": floor["id"], "enabled": True},
        ).json()
        cam_ids.append(c["id"])

    # точку относим к ближайшей камере (для будущей склейки путей по камерам)
    per_cam: dict[int, list] = {cid: [] for cid in cam_ids}
    fps = lab["fps"]
    for k, frame in enumerate(lab["frames"]):
        ts = (start_utc + timedelta(seconds=k / fps)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for track, x, y, _inside in frame["p"]:
            near = min(range(len(lab["cameras"])),
                       key=lambda i: (lab["cameras"][i]["position"][0] - x) ** 2 + (lab["cameras"][i]["position"][1] - y) ** 2)
            u, v = to_plan(b, x, y)
            per_cam[cam_ids[near]].append({"track_id": max(track, 0), "ts": ts, "x": round(u, 5), "y": round(v, 5)})

    total = 0
    for cid, pts in per_cam.items():
        for i in range(0, len(pts), 5000):
            requests.post(f"{api}/ingest", json={"camera_id": cid, "tracks": pts[i:i + 5000]}).raise_for_status()
        total += len(pts)
    print(f"загружено точек: {total}; запись {start_local:%d.%m.%Y %H:%M}–"
          f"{(start_local + timedelta(seconds=lab['duration'])):%H:%M} по времени ТЦ")


if __name__ == "__main__":
    main()
