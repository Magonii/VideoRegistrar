"""Демо-режим: наполняет БД структурой ТЦ и неделей истории, затем в реальном времени
генерирует события, как будто работают камеры. Нужен, чтобы разрабатывать и показывать
интерфейс без видеопотоков."""
import asyncio
import logging
import math
import random
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from .config import DATA_DIR, DEMO_CLOSE_HOUR, DEMO_OPEN_HOUR
from .db import SessionLocal
from .models import (
    AlertRule,
    Camera,
    CrossingEvent,
    Floor,
    Line,
    QueueSnapshot,
    Setting,
    TrackPoint,
    Zone,
)
from .timeutil import day_start_n_days_ago, from_local, to_local, utcnow

log = logging.getLogger("demo")

HOURLY_WEIGHTS = [0.4, 0.6, 0.8, 0.9, 0.8, 0.7, 0.8, 0.9, 1.0, 1.1, 0.9, 0.5]
BACKFILL_DAYS = 7
BACKFILL_STEP = 300  # секунд

# (x, y, разброс x, разброс y, вес, функция пика по часу или None)
HOTSPOTS: dict[int, list[tuple]] = {
    1: [
        (0.05, 0.50, 0.03, 0.06, 3.0, None),  # западный вход
        (0.95, 0.50, 0.03, 0.06, 2.0, None),  # восточный вход
        (0.50, 0.50, 0.08, 0.10, 4.0, None),  # атриум
        (0.22, 0.80, 0.07, 0.05, 2.5, lambda h: 0.3 + 2.5 * math.exp(-((h - 19) ** 2) / 4)),  # кинотеатр
        (0.72, 0.18, 0.08, 0.06, 2.5, None),  # якорный магазин
        (0.30, 0.20, 0.07, 0.06, 1.5, None),
        (0.78, 0.82, 0.08, 0.05, 1.5, None),
    ],
    2: [
        (0.50, 0.50, 0.05, 0.08, 3.0, None),  # эскалаторы
        (0.72, 0.28, 0.10, 0.08, 4.0, lambda h: 0.2 + 3 * math.exp(-((h - 13) ** 2) / 2) + 2.5 * math.exp(-((h - 19) ** 2) / 3)),  # фудкорт
        (0.20, 0.22, 0.08, 0.06, 1.5, None),
        (0.25, 0.80, 0.08, 0.05, 1.5, None),
        (0.80, 0.80, 0.07, 0.05, 1.2, None),
    ],
}

PLAN_SHOPS = {
    1: (["Zara", "H&M", "Спорт", "Обувь", "Аптека", "Банк"], ["Кинотеатр", "Электроника", "Детский мир", "Кофейня", "Книги", "Парфюм"]),
    2: (["Кино: залы", "Игры", "Одежда", "Сервис", "Бытовая", "Мебель"], ["Рестораны", "Фудкорт", "Фудкорт", "Кофе", "Пекарня", "Десерты"]),
}


def make_plan_svg(floor_no: int, title: str) -> str:
    top, bottom = PLAN_SHOPS[floor_no]
    rects = []
    for row, (names, y, h) in enumerate(((top, 40, 190), (bottom, 395, 190))):
        w = 1000 / len(names)
        for i, name in enumerate(names):
            x = i * w
            rects.append(
                f'<rect x="{x + 6:.0f}" y="{y}" width="{w - 12:.0f}" height="{h}" rx="6" fill="#e6eaf0" stroke="#c4ccd8"/>'
                f'<text x="{x + w / 2:.0f}" y="{y + h / 2:.0f}" text-anchor="middle" font-family="sans-serif" '
                f'font-size="17" fill="#5b6675">{escape(name)}</text>'
            )
    extra = (
        '<circle cx="500" cy="312" r="62" fill="#d8dee8" stroke="#b5bfce"/>'
        '<text x="500" y="318" text-anchor="middle" font-family="sans-serif" font-size="15" fill="#5b6675">'
        + ("Атриум" if floor_no == 1 else "Эскалаторы")
        + "</text>"
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="625" viewBox="0 0 1000 625">'
        '<rect width="1000" height="625" fill="#f7f8fa"/>'
        '<rect x="0" y="240" width="1000" height="145" fill="#ffffff"/>'
        + "".join(rects)
        + extra
        + f'<text x="14" y="24" font-family="sans-serif" font-size="16" font-weight="600" fill="#2b3340">{title}</text>'
        "</svg>"
    )


def poisson(lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(random.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= random.random()
        if p <= limit:
            return k
        k += 1


def seed_structure(db: Session) -> None:
    f1 = Floor(name="1 этаж", sort=1, capacity=2200)
    f2 = Floor(name="2 этаж", sort=2, capacity=1500)
    db.add_all([f1, f2])
    db.flush()

    plans = DATA_DIR / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    for n, floor in ((1, f1), (2, f2)):
        (plans / f"floor_{floor.id}.svg").write_text(make_plan_svg(n, floor.name), encoding="utf-8")
        floor.plan_path = f"floor_{floor.id}.svg"

    cams = [
        Camera(name="Главный вход (запад)", floor_id=f1.id, rtsp_url="rtsp://demo/west"),
        Camera(name="Вход (восток)", floor_id=f1.id, rtsp_url="rtsp://demo/east"),
        Camera(name="Эскалаторы 1→2", floor_id=f2.id, rtsp_url="rtsp://demo/escalator"),
        Camera(name="Фудкорт — кассы", floor_id=f2.id, rtsp_url="rtsp://demo/foodcourt"),
        Camera(name="Кинотеатр — касса", floor_id=f1.id, rtsp_url="rtsp://demo/cinema"),
    ]
    db.add_all(cams)
    db.flush()
    west, east, esc, food, cinema = cams

    db.add_all(
        [
            Line(camera_id=west.id, name="Западный вход", p1=[0.15, 0.55], p2=[0.85, 0.55], in_side=1, floor_in_id=f1.id),
            Line(camera_id=east.id, name="Восточный вход", p1=[0.15, 0.55], p2=[0.85, 0.55], in_side=1, floor_in_id=f1.id),
            Line(camera_id=esc.id, name="Эскалатор 1→2", p1=[0.2, 0.5], p2=[0.8, 0.5], in_side=1, floor_in_id=f2.id, floor_out_id=f1.id),
            Zone(camera_id=food.id, name="Фудкорт — кассы", kind="queue", floor_id=f2.id, min_dwell_sec=8,
                 polygon=[[0.2, 0.3], [0.8, 0.3], [0.8, 0.9], [0.2, 0.9]]),
            Zone(camera_id=cinema.id, name="Кинотеатр — касса", kind="queue", floor_id=f1.id, min_dwell_sec=8,
                 polygon=[[0.25, 0.35], [0.75, 0.35], [0.75, 0.9], [0.25, 0.9]]),
            Setting(key="mall_capacity", value="3500"),
            AlertRule(name="ТЦ почти заполнен (>85%)", metric="occupancy_mall", threshold=2975, min_duration_sec=120),
            AlertRule(name="Длинная очередь", metric="queue_people", threshold=9, min_duration_sec=60),
            AlertRule(name="Долгое ожидание в очереди", metric="queue_wait", threshold=300, min_duration_sec=60),
        ]
    )
    db.commit()


class Simulator:
    def __init__(self, db: Session) -> None:
        lines = list(db.scalars(select(Line).order_by(Line.id)))
        self.entrances = [ln for ln in lines if ln.floor_out_id is None]
        self.escalator = next(ln for ln in lines if ln.floor_out_id is not None)
        self.f1_id, self.f2_id = self.entrances[0].floor_in_id, self.escalator.floor_in_id
        self.queue_zones = list(db.scalars(select(Zone).where(Zone.kind == "queue")))
        cams = {c.floor_id: c.id for c in db.scalars(select(Camera))}
        self.camera_by_floor = cams
        self.f1 = 0.0  # людей на 1 этаже
        self.f2 = 0.0

    def day_rate(self, local: datetime) -> float:
        """Заходов в секунду в данный момент."""
        daily = 12000 if local.weekday() >= 5 else 8000
        h = local.hour + local.minute / 60
        span = DEMO_CLOSE_HOUR - DEMO_OPEN_HOUR
        idx = min(len(HOURLY_WEIGHTS) - 1, int((h - DEMO_OPEN_HOUR) / span * len(HOURLY_WEIGHTS)))
        return daily * HOURLY_WEIGHTS[idx] / sum(HOURLY_WEIGHTS) * len(HOURLY_WEIGHTS) / span / 3600

    def step(self, now: datetime, dt: float, with_queue: bool) -> dict:
        local = to_local(now - timedelta(seconds=dt / 2))  # по середине шага, чтобы события не «вылезали» за открытие
        h = local.hour + local.minute / 60
        is_open = DEMO_OPEN_HOUR <= h < DEMO_CLOSE_HOUR
        closing = DEMO_CLOSE_HOUR <= h < DEMO_CLOSE_HOUR + 1
        out = {"crossings": [], "tracks": [], "queues": []}
        if not is_open and not closing:
            self.f1 = self.f2 = 0.0
            return out

        m = dt / 60
        ins = poisson(self.day_rate(local) * dt) if is_open else 0
        ups = min(self.f1, poisson(self.f1 * (0.015 if is_open else 0) * m))
        downs = min(self.f2, poisson(self.f2 * (0.02 if is_open else 0.15) * m))
        outs = min(self.f1 + downs, poisson(self.f1 * (0.012 if is_open else 0.10) * m))
        self.f1 += ins - ups + downs - outs
        self.f2 += ups - downs
        self.f1, self.f2 = max(0.0, self.f1), max(0.0, self.f2)

        def at() -> datetime:
            return now - timedelta(seconds=random.uniform(0, dt))

        def emit(line: Line, direction: str, n: int) -> None:
            if n > 0:
                out["crossings"].append(
                    {"ts": at(), "line_id": line.id, "direction": direction, "count": n}
                )

        split = random.uniform(0.6, 0.7)
        w, e = self.entrances[0], self.entrances[-1]
        emit(w, "in", round(ins * split))
        emit(e, "in", ins - round(ins * split))
        emit(w, "out", round(outs * split))
        emit(e, "out", outs - round(outs * split))
        emit(self.escalator, "in", ups)
        emit(self.escalator, "out", downs)

        for floor_id, load in ((self.f1_id, self.f1), (self.f2_id, self.f2)):
            cam_id = self.camera_by_floor.get(floor_id, 0)
            for _ in range(poisson(load * 0.00008 * dt)):
                spots = HOTSPOTS[floor_id if floor_id in HOTSPOTS else 1]
                weights = [s[4] * (s[5](h) if s[5] else 1.0) for s in spots]
                if random.random() < 0.25:  # часть людей просто идёт по коридору
                    x, y = random.random(), 0.5 + random.gauss(0, 0.035)
                else:
                    sx, sy, dx, dy, _, _ = random.choices(spots, weights)[0]
                    x, y = random.gauss(sx, dx), random.gauss(sy, dy)
                out["tracks"].append(
                    {"ts": at(), "floor_id": floor_id, "camera_id": cam_id, "track_id": random.randint(1, 10**6),
                     "x": min(0.999, max(0.0, x)), "y": min(0.999, max(0.0, y))}
                )

        if with_queue and is_open:
            total = self.f1 + self.f2
            for zone in self.queue_zones:
                peak = (
                    0.25 + 1.6 * math.exp(-((h - 13) ** 2) / 2) + 1.2 * math.exp(-((h - 19) ** 2) / 3)
                    if zone.floor_id == self.f2_id
                    else 0.2 + 1.8 * math.exp(-((h - 19.5) ** 2) / 2.5)
                )
                people = poisson(0.6 + 7.5 * peak * min(1.6, total / 2000))
                wait = people * random.uniform(25, 55) if people else 0
                out["queues"].append({"ts": now, "zone_id": zone.id, "people": people, "max_wait_sec": wait})
        return out


def flush(db: Session, batch: dict) -> None:
    if batch["crossings"]:
        db.execute(insert(CrossingEvent), batch["crossings"])
    if batch["tracks"]:
        db.execute(insert(TrackPoint), batch["tracks"])
    if batch["queues"]:
        db.execute(insert(QueueSnapshot), batch["queues"])


def backfill(db: Session, sim: Simulator, now: datetime) -> None:
    log.info("demo: генерирую историю за %d дней", BACKFILL_DAYS)
    for days_ago in range(BACKFILL_DAYS, -1, -1):
        day_start = day_start_n_days_ago(now, days_ago)
        sim.f1 = sim.f2 = 0.0
        t = day_start
        day_end = min(day_start + timedelta(days=1), now)
        step_no = 0
        while t < day_end:
            t += timedelta(seconds=BACKFILL_STEP)
            step_no += 1
            # снимки очередей — раз в 5 минут в истории
            flush(db, sim.step(min(t, day_end), BACKFILL_STEP, with_queue=True))
        db.commit()


def seed_if_empty(db: Session) -> Simulator:
    if db.scalars(select(Floor).limit(1)).first() is None:
        seed_structure(db)
        sim = Simulator(db)
        backfill(db, sim, utcnow())
        return sim
    sim = Simulator(db)
    from .services.occupancy import compute_occupancy

    occ = compute_occupancy(db)
    sim.f1, sim.f2 = float(occ.get(sim.f1_id, 0)), float(occ.get(sim.f2_id, 0))
    return sim


async def run_demo(interval: float = 5.0) -> None:
    def _init() -> Simulator:
        with SessionLocal() as db:
            return seed_if_empty(db)

    sim = await asyncio.to_thread(_init)
    last = utcnow()
    tick = 0

    def _tick(now: datetime, dt: float, with_queue: bool) -> None:
        with SessionLocal() as db:
            flush(db, sim.step(now, dt, with_queue))
            for cam in db.scalars(select(Camera)):
                cam.last_seen = now
            db.commit()

    while True:
        await asyncio.sleep(interval)
        now = utcnow()
        tick += 1
        try:
            await asyncio.to_thread(_tick, now, (now - last).total_seconds(), True)
        except Exception:
            log.exception("demo tick failed")
        last = now
