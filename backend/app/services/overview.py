from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import QUEUE_STALE_SEC
from ..models import AlertEvent, Floor, QueueSnapshot, Zone
from ..timeutil import iso, local_day_start_utc, utcnow
from .occupancy import compute_occupancy, mall_capacity, visitors_between


def current_queues(db: Session, now: datetime | None = None) -> list[dict]:
    now = now or utcnow()
    result = []
    for zone in db.scalars(select(Zone).where(Zone.kind == "queue").order_by(Zone.id)):
        snap = db.scalars(
            select(QueueSnapshot).where(QueueSnapshot.zone_id == zone.id).order_by(QueueSnapshot.ts.desc()).limit(1)
        ).first()
        stale = snap is None or (now - snap.ts).total_seconds() > QUEUE_STALE_SEC
        result.append(
            {
                "zone_id": zone.id,
                "name": zone.name,
                "floor_id": zone.floor_id,
                "camera_id": zone.camera_id,
                "people": 0 if stale else snap.people,
                "max_wait_sec": 0 if stale else round(snap.max_wait_sec),
                "stale": stale,
                "ts": iso(snap.ts) if snap else None,
            }
        )
    return result


def active_alerts(db: Session) -> list[dict]:
    rows = db.scalars(select(AlertEvent).where(AlertEvent.resolved_at.is_(None)).order_by(AlertEvent.started_at.desc()))
    return [
        {
            "id": a.id,
            "rule_id": a.rule_id,
            "rule_name": a.rule_name,
            "started_at": iso(a.started_at),
            "peak_value": a.peak_value,
            "message": a.message,
        }
        for a in rows
    ]


def build_overview(db: Session) -> dict:
    now = utcnow()
    occ = compute_occupancy(db, now)
    floors = db.scalars(select(Floor).order_by(Floor.sort, Floor.id)).all()

    day_start = local_day_start_utc(now)
    elapsed = now - day_start
    yesterday_start = day_start - timedelta(days=1)

    return {
        "ts": iso(now),
        "occupancy": {
            "mall": sum(occ.values()),
            "mall_capacity": mall_capacity(db),
            "floors": [
                {"id": f.id, "name": f.name, "occupancy": occ.get(f.id, 0), "capacity": f.capacity} for f in floors
            ],
        },
        "visitors_today": visitors_between(db, day_start, now),
        "visitors_yesterday_same_time": visitors_between(db, yesterday_start, yesterday_start + elapsed),
        "queues": current_queues(db, now),
        "alerts": active_alerts(db),
    }
