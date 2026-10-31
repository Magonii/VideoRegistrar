from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import CAMERA_ONLINE_SEC, DATA_DIR
from ..db import get_db
from ..models import AlertEvent, AlertRule, Camera, Floor, Line, OccupancyCorrection, Setting, TrackPoint, Zone
from ..schemas import (
    AlertEventOut,
    CameraIn,
    CameraOut,
    CorrectionIn,
    FloorIn,
    FloorOut,
    LayoutIn,
    RuleIn,
    RuleOut,
    SettingsModel,
)
from ..services.occupancy import mall_capacity
from ..timeutil import utcnow

router = APIRouter(prefix="/api")

PLANS_DIR = DATA_DIR / "plans"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
MEDIA_TYPES = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} не найден(а)")


# ---- этажи ------------------------------------------------------------------


@router.get("/floors", response_model=list[FloorOut])
def list_floors(db: Session = Depends(get_db)):
    return db.scalars(select(Floor).order_by(Floor.sort, Floor.id)).all()


@router.post("/floors", response_model=FloorOut)
def create_floor(body: FloorIn, db: Session = Depends(get_db)):
    floor = Floor(**body.model_dump())
    db.add(floor)
    db.commit()
    return floor


@router.put("/floors/{floor_id}", response_model=FloorOut)
def update_floor(floor_id: int, body: FloorIn, db: Session = Depends(get_db)):
    floor = db.get(Floor, floor_id)
    if not floor:
        raise _not_found("Этаж")
    for k, v in body.model_dump().items():
        setattr(floor, k, v)
    db.commit()
    return floor


@router.delete("/floors/{floor_id}", status_code=204)
def delete_floor(floor_id: int, db: Session = Depends(get_db)):
    floor = db.get(Floor, floor_id)
    if not floor:
        raise _not_found("Этаж")
    in_use = db.scalars(select(Camera.id).where(Camera.floor_id == floor_id).limit(1)).first()
    if in_use:
        raise HTTPException(409, "К этажу привязаны камеры — сначала перенесите или удалите их")
    db.delete(floor)
    db.commit()


@router.delete("/floors/{floor_id}/tracks")
def clear_floor_tracks(floor_id: int, db: Session = Depends(get_db)):
    """Удаляет точки треков этажа (данные тепловой карты), например перед повторным импортом."""
    if not db.get(Floor, floor_id):
        raise _not_found("Этаж")
    deleted = db.execute(delete(TrackPoint).where(TrackPoint.floor_id == floor_id)).rowcount
    db.commit()
    return {"deleted": deleted}


@router.post("/floors/{floor_id}/plan", response_model=FloorOut)
async def upload_plan(floor_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    floor = db.get(Floor, floor_id)
    if not floor:
        raise _not_found("Этаж")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in MEDIA_TYPES:
        raise HTTPException(400, "Допустимы форматы: svg, png, jpg, webp")
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"floor_{floor_id}{ext}"
    for old in PLANS_DIR.glob(f"floor_{floor_id}.*"):
        old.unlink()
    (PLANS_DIR / name).write_bytes(await file.read())
    floor.plan_path = name
    db.commit()
    return floor


@router.get("/floors/{floor_id}/plan")
def get_plan(floor_id: int, db: Session = Depends(get_db)):
    floor = db.get(Floor, floor_id)
    if not floor or not floor.plan_path or not (PLANS_DIR / floor.plan_path).exists():
        raise _not_found("План этажа")
    path = PLANS_DIR / floor.plan_path
    return FileResponse(path, media_type=MEDIA_TYPES.get(path.suffix.lower()), headers={"Cache-Control": "no-cache"})


# ---- камеры -----------------------------------------------------------------


def camera_out(cam: Camera) -> CameraOut:
    online = cam.last_seen is not None and (utcnow() - cam.last_seen) <= timedelta(seconds=CAMERA_ONLINE_SEC)
    return CameraOut(
        id=cam.id,
        name=cam.name,
        rtsp_url=cam.rtsp_url,
        floor_id=cam.floor_id,
        enabled=cam.enabled,
        homography=cam.homography,
        online=online,
        has_snapshot=bool(cam.snapshot_path),
        last_seen=cam.last_seen,
        lines=cam.lines,
        zones=cam.zones,
    )


@router.get("/cameras", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    return [camera_out(c) for c in db.scalars(select(Camera).order_by(Camera.id))]


@router.post("/cameras", response_model=CameraOut)
def create_camera(body: CameraIn, db: Session = Depends(get_db)):
    cam = Camera(**body.model_dump())
    db.add(cam)
    db.commit()
    return camera_out(cam)


@router.get("/cameras/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise _not_found("Камера")
    return camera_out(cam)


@router.put("/cameras/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraIn, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise _not_found("Камера")
    for k, v in body.model_dump().items():
        setattr(cam, k, v)
    db.commit()
    return camera_out(cam)


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise _not_found("Камера")
    db.delete(cam)
    db.commit()


@router.put("/cameras/{camera_id}/layout", response_model=CameraOut)
def save_layout(camera_id: int, body: LayoutIn, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise _not_found("Камера")

    def sync(existing, incoming, model):
        by_id = {e.id: e for e in existing}
        keep = set()
        for item in incoming:
            data = item.model_dump(exclude={"id"})
            if item.id and item.id in by_id:
                for k, v in data.items():
                    setattr(by_id[item.id], k, v)
                keep.add(item.id)
            else:
                db.add(model(camera_id=camera_id, **data))
        for e in existing:
            if e.id not in keep:
                db.delete(e)

    sync(list(cam.lines), body.lines, Line)
    sync(list(cam.zones), body.zones, Zone)
    db.commit()
    db.refresh(cam)
    return camera_out(cam)


@router.post("/cameras/{camera_id}/snapshot", status_code=204)
async def upload_snapshot(camera_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise _not_found("Камера")
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    name = f"camera_{camera_id}.jpg"
    (SNAPSHOTS_DIR / name).write_bytes(await file.read())
    cam.snapshot_path = name
    cam.last_seen = utcnow()
    db.commit()


@router.get("/cameras/{camera_id}/snapshot")
def get_snapshot(camera_id: int, db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam or not cam.snapshot_path or not (SNAPSHOTS_DIR / cam.snapshot_path).exists():
        raise _not_found("Снимок")
    return FileResponse(SNAPSHOTS_DIR / cam.snapshot_path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


# ---- правила и журнал алертов --------------------------------------------------


@router.get("/alert-rules", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)):
    return db.scalars(select(AlertRule).order_by(AlertRule.id)).all()


@router.post("/alert-rules", response_model=RuleOut)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    rule = AlertRule(**body.model_dump())
    db.add(rule)
    db.commit()
    return rule


@router.put("/alert-rules/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, body: RuleIn, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise _not_found("Правило")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    db.commit()
    return rule


@router.delete("/alert-rules/{rule_id}", status_code=204)
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise _not_found("Правило")
    db.delete(rule)
    db.commit()


@router.get("/alerts", response_model=list[AlertEventOut])
def list_alerts(limit: int = 100, db: Session = Depends(get_db)):
    return db.scalars(select(AlertEvent).order_by(AlertEvent.started_at.desc()).limit(min(limit, 500))).all()


# ---- настройки ---------------------------------------------------------------


@router.get("/settings", response_model=SettingsModel)
def get_settings(db: Session = Depends(get_db)):
    return SettingsModel(mall_capacity=mall_capacity(db))


@router.put("/settings", response_model=SettingsModel)
def put_settings(body: SettingsModel, db: Session = Depends(get_db)):
    row = db.get(Setting, "mall_capacity")
    value = str(body.mall_capacity) if body.mall_capacity else ""
    if row:
        row.value = value
    else:
        db.add(Setting(key="mall_capacity", value=value))
    db.commit()
    return SettingsModel(mall_capacity=mall_capacity(db))


@router.post("/occupancy/correct", status_code=204)
def correct_occupancy(body: CorrectionIn, db: Session = Depends(get_db)):
    """Ручная поправка: «сейчас на этаже N человек»; дальше счёт идёт от этого значения."""
    if not db.get(Floor, body.floor_id):
        raise _not_found("Этаж")
    db.add(OccupancyCorrection(floor_id=body.floor_id, value=body.value, ts=utcnow()))
    db.commit()
