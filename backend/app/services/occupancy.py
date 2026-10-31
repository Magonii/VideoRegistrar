"""Заполняемость и трафик из событий пересечения линий.

Каждое событие переводит людей из «источника» в «приёмник» (этаж или None = улица):
  direction == "in":  floor_out_id -> floor_in_id
  direction == "out": floor_in_id  -> floor_out_id
Заполняемость этажа — накопленный баланс с начала дня (или с последней ручной поправки).
Заполняемость ТЦ — сумма по этажам.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CrossingEvent, Floor, Line, OccupancyCorrection, Setting
from ..timeutil import from_local, local_day_start_utc, to_local, utcnow


def endpoints(line: Line, direction: str) -> tuple[int | None, int | None]:
    if direction == "in":
        return line.floor_out_id, line.floor_in_id
    return line.floor_in_id, line.floor_out_id


def scope_delta(src: int | None, dst: int | None, scope_floor: int | None) -> tuple[int, int]:
    """(вошло, вышло) для одного человека в рамках выбранной области.

    scope_floor=None — весь ТЦ (вход с улицы / выход на улицу)."""
    if scope_floor is None:
        return (1 if src is None and dst is not None else 0, 1 if dst is None and src is not None else 0)
    return (1 if dst == scope_floor else 0, 1 if src == scope_floor else 0)


def compute_occupancy(db: Session, now: datetime | None = None) -> dict[int, int]:
    now = now or utcnow()
    day_start = local_day_start_utc(now)
    floors = db.scalars(select(Floor)).all()

    base: dict[int, int] = {}
    since: dict[int, datetime] = {}
    for f in floors:
        corr = db.scalars(
            select(OccupancyCorrection)
            .where(OccupancyCorrection.floor_id == f.id, OccupancyCorrection.ts >= day_start)
            .order_by(OccupancyCorrection.ts.desc())
            .limit(1)
        ).first()
        base[f.id] = corr.value if corr else 0
        since[f.id] = corr.ts if corr else day_start

    lines = {ln.id: ln for ln in db.scalars(select(Line))}
    rows = db.execute(
        select(CrossingEvent.ts, CrossingEvent.line_id, CrossingEvent.direction, CrossingEvent.count).where(
            CrossingEvent.ts >= day_start
        )
    ).all()

    occ = dict(base)
    for ts, line_id, direction, count in rows:
        line = lines.get(line_id)
        if line is None:
            continue
        src, dst = endpoints(line, direction)
        if dst in occ and ts >= since[dst]:
            occ[dst] += count
        if src in occ and ts >= since[src]:
            occ[src] -= count
    return {fid: max(0, v) for fid, v in occ.items()}


def visitors_between(db: Session, start: datetime, end: datetime) -> int:
    """Сколько людей вошло в ТЦ с улицы за интервал."""
    lines = {ln.id: ln for ln in db.scalars(select(Line))}
    rows = db.execute(
        select(CrossingEvent.line_id, CrossingEvent.direction, CrossingEvent.count).where(
            CrossingEvent.ts >= start, CrossingEvent.ts < end
        )
    ).all()
    total = 0
    for line_id, direction, count in rows:
        line = lines.get(line_id)
        if line is None:
            continue
        entered, _ = scope_delta(*endpoints(line, direction), None)
        total += entered * count
    return total


def get_setting(db: Session, key: str) -> str | None:
    row = db.get(Setting, key)
    return row.value if row else None


def mall_capacity(db: Session) -> int | None:
    v = get_setting(db, "mall_capacity")
    return int(v) if v else None


def traffic_series(
    db: Session, start: datetime, end: datetime, bucket: str, scope_floor: int | None
) -> list[dict]:
    """Вход/выход по часовым или дневным корзинам (в часовом поясе ТЦ).

    Для часовых корзин добавляется `occupancy` — заполняемость на конец часа
    (накопление с начала каждого дня)."""
    step = timedelta(hours=1) if bucket == "hour" else timedelta(days=1)

    def floor_bucket(local_dt: datetime) -> datetime:
        if bucket == "hour":
            return local_dt.replace(minute=0, second=0, microsecond=0)
        return local_dt.replace(hour=0, minute=0, second=0, microsecond=0)

    first_day = local_day_start_utc(start)
    lines = {ln.id: ln for ln in db.scalars(select(Line))}
    rows = db.execute(
        select(CrossingEvent.ts, CrossingEvent.line_id, CrossingEvent.direction, CrossingEvent.count).where(
            CrossingEvent.ts >= first_day, CrossingEvent.ts < end
        )
    ).all()

    acc: dict[datetime, list[int]] = {}
    for ts, line_id, direction, count in rows:
        line = lines.get(line_id)
        if line is None:
            continue
        entered, left = scope_delta(*endpoints(line, direction), scope_floor)
        if not entered and not left:
            continue
        slot = acc.setdefault(floor_bucket(to_local(ts)), [0, 0])
        slot[0] += entered * count
        slot[1] += left * count

    local_start = floor_bucket(to_local(first_day if bucket == "hour" else start))
    local_end = to_local(end)
    visible_from = floor_bucket(to_local(start))

    out: list[dict] = []
    running = 0
    cur = local_start
    last_day = cur.date()
    while cur < local_end:
        if cur.date() != last_day:
            running, last_day = 0, cur.date()
        i, o = acc.get(cur, (0, 0))
        running = max(0, running + i - o)
        if cur >= visible_from:
            out.append(
                {
                    "ts": from_local(cur),
                    "in": i,
                    "out": o,
                    "occupancy": running if bucket == "hour" else None,
                }
            )
        cur += step
    return out
