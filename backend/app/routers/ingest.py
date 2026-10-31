from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, CrossingEvent, QueueSnapshot, TrackPoint
from ..schemas import IngestBatch
from ..timeutil import utcnow

router = APIRouter(prefix="/api")


@router.post("/ingest")
def ingest(batch: IngestBatch, db: Session = Depends(get_db)):
    """Пакет событий от vision-worker одной камеры. Любой запрос (даже пустой) — это heartbeat."""
    cam = db.get(Camera, batch.camera_id)
    if not cam:
        raise HTTPException(404, "Камера не найдена")
    now = utcnow()
    cam.last_seen = now

    if batch.crossings:
        db.execute(
            insert(CrossingEvent),
            [
                {"ts": c.ts or now, "line_id": c.line_id, "direction": c.direction, "count": c.count}
                for c in batch.crossings
            ],
        )
    if batch.queues:
        db.execute(
            insert(QueueSnapshot),
            [
                {"ts": q.ts or now, "zone_id": q.zone_id, "people": q.people, "max_wait_sec": q.max_wait_sec}
                for q in batch.queues
            ],
        )
    if batch.tracks and cam.floor_id is not None:
        db.execute(
            insert(TrackPoint),
            [
                {
                    "ts": t.ts or now,
                    "floor_id": cam.floor_id,
                    "camera_id": cam.id,
                    "track_id": t.track_id,
                    "x": min(1.0, max(0.0, t.x)),
                    "y": min(1.0, max(0.0, t.y)),
                }
                for t in batch.tracks
            ],
        )
    db.commit()
    return {"ok": True, "crossings": len(batch.crossings), "queues": len(batch.queues), "tracks": len(batch.tracks)}
