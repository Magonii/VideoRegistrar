from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Floor, QueueSnapshot, TrackPoint, Zone
from ..services.occupancy import traffic_series
from ..services.overview import build_overview, current_queues
from ..timeutil import iso, norm_utc, utcnow

router = APIRouter(prefix="/api")


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    return build_overview(db)


@router.get("/traffic")
def traffic(
    start: datetime = Query(alias="from"),
    end: datetime = Query(alias="to"),
    bucket: Literal["hour", "day"] = "hour",
    floor_id: int | None = None,
    db: Session = Depends(get_db),
):
    start, end = norm_utc(start), norm_utc(end)
    if end <= start:
        raise HTTPException(400, "Параметр to должен быть позже from")
    if (end - start) > timedelta(days=370):
        raise HTTPException(400, "Максимальный период — 370 дней")
    series = traffic_series(db, start, end, bucket, floor_id)
    return [{**item, "ts": iso(item["ts"])} for item in series]


@router.get("/heatmap")
def heatmap(
    floor_id: int,
    start: datetime = Query(alias="from"),
    end: datetime = Query(alias="to"),
    cols: int = Query(80, ge=8, le=200),
    rows: int = Query(50, ge=8, le=200),
    db: Session = Depends(get_db),
):
    """Плотность присутствия: число точек треков в ячейках сетки cols×rows (координаты 0..1)."""
    if not db.get(Floor, floor_id):
        raise HTTPException(404, "Этаж не найден")
    start, end = norm_utc(start), norm_utc(end)
    # CAST float->int в SQLite отбрасывает дробную часть, а в PostgreSQL округляет, поэтому там нужен floor.
    pg = db.get_bind().dialect.name == "postgresql"
    cx = cast(func.floor(TrackPoint.x * cols) if pg else TrackPoint.x * cols, Integer)
    cy = cast(func.floor(TrackPoint.y * rows) if pg else TrackPoint.y * rows, Integer)
    q = (
        select(cx.label("cx"), cy.label("cy"), func.count().label("n"))
        .where(TrackPoint.floor_id == floor_id, TrackPoint.ts >= start, TrackPoint.ts < end)
        .group_by(cx, cy)
    )
    cells = [0] * (cols * rows)
    total = 0
    for gx, gy, n in db.execute(q):
        gx, gy = min(cols - 1, max(0, gx)), min(rows - 1, max(0, gy))
        cells[gy * cols + gx] += n
        total += n
    return {"cols": cols, "rows": rows, "cells": cells, "max": max(cells), "total": total}


@router.get("/queues")
def queues(db: Session = Depends(get_db)):
    return current_queues(db)


@router.get("/queues/{zone_id}/history")
def queue_history(
    zone_id: int,
    start: datetime | None = Query(None, alias="from"),
    end: datetime | None = Query(None, alias="to"),
    step_min: int = Query(5, ge=1, le=60),
    db: Session = Depends(get_db),
):
    if not db.get(Zone, zone_id):
        raise HTTPException(404, "Зона не найдена")
    end = norm_utc(end) if end else utcnow()
    start = norm_utc(start) if start else end - timedelta(hours=6)
    rows = db.execute(
        select(QueueSnapshot.ts, QueueSnapshot.people, QueueSnapshot.max_wait_sec)
        .where(QueueSnapshot.zone_id == zone_id, QueueSnapshot.ts >= start, QueueSnapshot.ts < end)
        .order_by(QueueSnapshot.ts)
    ).all()

    step = step_min * 60
    buckets: dict[int, list] = {}
    for ts, people, wait in rows:
        key = int(ts.replace(tzinfo=timezone.utc).timestamp()) // step * step
        b = buckets.setdefault(key, [0, 0, 0.0, 0])  # max people, sum people, max wait, n
        b[0] = max(b[0], people)
        b[1] += people
        b[2] = max(b[2], wait)
        b[3] += 1
    return [
        {
            "ts": iso(datetime.fromtimestamp(k, timezone.utc)),
            "people_max": b[0],
            "people_avg": round(b[1] / b[3], 1),
            "wait_max_sec": round(b[2]),
        }
        for k, b in sorted(buckets.items())
    ]
