from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .timeutil import utcnow


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Floor(Base):
    __tablename__ = "floors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    sort: Mapped[int] = mapped_column(default=0)
    capacity: Mapped[int | None] = mapped_column(default=None)
    plan_path: Mapped[str | None] = mapped_column(String(255), default=None)

    @property
    def has_plan(self) -> bool:
        return bool(self.plan_path)


class Camera(Base):
    __tablename__ = "cameras"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    rtsp_url: Mapped[str] = mapped_column(String(500), default="")
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"), default=None)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Матрица 3x3: нормализованные координаты кадра -> нормализованные координаты плана этажа.
    homography: Mapped[list | None] = mapped_column(JSON, default=None)
    snapshot_path: Mapped[str | None] = mapped_column(String(255), default=None)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    lines: Mapped[list["Line"]] = relationship(
        back_populates="camera", cascade="all, delete-orphan", order_by="Line.id"
    )
    zones: Mapped[list["Zone"]] = relationship(
        back_populates="camera", cascade="all, delete-orphan", order_by="Zone.id"
    )


class Line(Base):
    """Виртуальная линия подсчёта. Координаты нормализованы (0..1) относительно кадра.

    Сторона «внутрь» — та, где знак векторного произведения (p2-p1)×(p-p1) равен in_side.
    Пересечение линии в сторону in_side = событие «in»: человек уходит из floor_out_id
    (None = улица) в floor_in_id (None = улица).
    """

    __tablename__ = "lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    name: Mapped[str] = mapped_column(String(100))
    p1: Mapped[list] = mapped_column(JSON)
    p2: Mapped[list] = mapped_column(JSON)
    in_side: Mapped[int] = mapped_column(Integer, default=1)
    floor_in_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"), default=None)
    floor_out_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"), default=None)

    camera: Mapped[Camera] = relationship(back_populates="lines")


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(16), default="queue")  # queue | area
    polygon: Mapped[list] = mapped_column(JSON)
    floor_id: Mapped[int | None] = mapped_column(ForeignKey("floors.id"), default=None)
    # В очередь попадают только те, кто пробыл в зоне не меньше этого времени.
    min_dwell_sec: Mapped[int] = mapped_column(Integer, default=5)

    camera: Mapped[Camera] = relationship(back_populates="zones")


# События и измерения. На line_id / zone_id внешних ключей нет намеренно:
# история должна переживать удаление и перерисовку линий в редакторе.


class CrossingEvent(Base):
    __tablename__ = "crossing_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    line_id: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(3))  # in | out
    count: Mapped[int] = mapped_column(Integer, default=1)


class QueueSnapshot(Base):
    __tablename__ = "queue_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    zone_id: Mapped[int] = mapped_column(Integer, index=True)
    people: Mapped[int] = mapped_column(Integer)
    max_wait_sec: Mapped[float] = mapped_column(Float, default=0)


class TrackPoint(Base):
    """Точка трека в координатах плана этажа (0..1). Основа хитмапа; track_id и camera_id
    оставлены для будущей склейки путей (Re-ID)."""

    __tablename__ = "track_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, index=True)
    floor_id: Mapped[int] = mapped_column(Integer, index=True)
    camera_id: Mapped[int] = mapped_column(Integer)
    track_id: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)


class OccupancyCorrection(Base):
    """Ручная поправка заполняемости этажа: с момента ts считаем от value."""

    __tablename__ = "occupancy_corrections"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    floor_id: Mapped[int] = mapped_column(Integer, index=True)
    value: Mapped[int] = mapped_column(Integer)


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    # occupancy_mall | occupancy_floor | queue_people | queue_wait
    metric: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(default=None)  # этаж или зона; None = любая/весь ТЦ
    threshold: Mapped[float] = mapped_column(Float)
    min_duration_sec: Mapped[int] = mapped_column(Integer, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    notify: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    rule_id: Mapped[int] = mapped_column(Integer, index=True)
    rule_name: Mapped[str] = mapped_column(String(150))
    started_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    peak_value: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text, default="")
