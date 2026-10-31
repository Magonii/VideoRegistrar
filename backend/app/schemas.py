from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .timeutil import UtcDateTime


class FloorIn(BaseModel):
    name: str
    sort: int = 0
    capacity: int | None = None


class FloorOut(FloorIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    has_plan: bool


class LineIn(BaseModel):
    id: int | None = None
    name: str
    p1: list[float] = Field(min_length=2, max_length=2)
    p2: list[float] = Field(min_length=2, max_length=2)
    in_side: Literal[1, -1] = 1
    floor_in_id: int | None = None
    floor_out_id: int | None = None


class LineOut(LineIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int


class ZoneIn(BaseModel):
    id: int | None = None
    name: str
    kind: Literal["queue", "area"] = "queue"
    polygon: list[list[float]]
    floor_id: int | None = None
    min_dwell_sec: int = 5


class ZoneOut(ZoneIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    camera_id: int


class CameraIn(BaseModel):
    name: str
    rtsp_url: str = ""
    floor_id: int | None = None
    enabled: bool = True
    homography: list[list[float]] | None = None


class CameraOut(CameraIn):
    id: int
    online: bool
    has_snapshot: bool
    last_seen: UtcDateTime | None = None
    lines: list[LineOut] = []
    zones: list[ZoneOut] = []


class LayoutIn(BaseModel):
    """Полный набор линий и зон камеры. Элементы с id обновляются, без id создаются,
    отсутствующие в списке удаляются."""

    lines: list[LineIn] = []
    zones: list[ZoneIn] = []


# ---- приём данных от worker ------------------------------------------------


class CrossingIn(BaseModel):
    line_id: int
    direction: Literal["in", "out"]
    ts: UtcDateTime | None = None
    count: int = Field(default=1, ge=1)


class QueueIn(BaseModel):
    zone_id: int
    people: int = Field(ge=0)
    max_wait_sec: float = Field(default=0, ge=0)
    ts: UtcDateTime | None = None


class TrackIn(BaseModel):
    track_id: int
    ts: UtcDateTime | None = None
    x: float
    y: float


class IngestBatch(BaseModel):
    camera_id: int
    crossings: list[CrossingIn] = []
    queues: list[QueueIn] = []
    tracks: list[TrackIn] = []


# ---- алерты и настройки ----------------------------------------------------

Metric = Literal["occupancy_mall", "occupancy_floor", "queue_people", "queue_wait"]


class RuleIn(BaseModel):
    name: str
    metric: Metric
    target_id: int | None = None
    threshold: float
    min_duration_sec: int = Field(default=60, ge=0)
    enabled: bool = True
    notify: bool = True


class RuleOut(RuleIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AlertEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rule_id: int
    rule_name: str
    started_at: UtcDateTime
    resolved_at: UtcDateTime | None
    peak_value: float
    message: str


class SettingsModel(BaseModel):
    mall_capacity: int | None = None


class CorrectionIn(BaseModel):
    floor_id: int
    value: int = Field(ge=0)
