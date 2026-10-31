"""Движок алертов: правило срабатывает, когда метрика выше порога дольше min_duration_sec,
и закрывается, когда значение опустится ниже 90% порога (гистерезис против «дребезга»)."""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AlertEvent, AlertRule, Floor, Zone
from ..timeutil import utcnow
from .notify import send_notification
from .occupancy import compute_occupancy
from .overview import current_queues

log = logging.getLogger("alerts")

METRIC_LABELS = {
    "occupancy_mall": "Заполняемость ТЦ",
    "occupancy_floor": "Заполняемость этажа",
    "queue_people": "Очередь, человек",
    "queue_wait": "Ожидание в очереди, сек",
}


class AlertEngine:
    def __init__(self) -> None:
        self._breach_since: dict[int, datetime] = {}

    def metric_value(self, db: Session, rule: AlertRule, occ: dict[int, int], queues: list[dict]) -> float:
        if rule.metric == "occupancy_mall":
            return float(sum(occ.values()))
        if rule.metric == "occupancy_floor":
            return float(occ.get(rule.target_id, 0)) if rule.target_id else float(max(occ.values(), default=0))
        scoped = [q for q in queues if rule.target_id is None or q["zone_id"] == rule.target_id]
        if not scoped:
            return 0.0
        key = "people" if rule.metric == "queue_people" else "max_wait_sec"
        return float(max(q[key] for q in scoped))

    def describe(self, db: Session, rule: AlertRule, value: float) -> str:
        where = ""
        if rule.target_id:
            if rule.metric == "occupancy_floor":
                floor = db.get(Floor, rule.target_id)
                where = f" ({floor.name})" if floor else ""
            elif rule.metric.startswith("queue"):
                zone = db.get(Zone, rule.target_id)
                where = f" ({zone.name})" if zone else ""
        return f"{rule.name}: {METRIC_LABELS[rule.metric]}{where} = {value:g} при пороге {rule.threshold:g}"

    def tick(self, db: Session, now: datetime | None = None) -> None:
        now = now or utcnow()
        rules = db.scalars(select(AlertRule)).all()
        occ = compute_occupancy(db, now)
        queues = current_queues(db, now)

        for rule in rules:
            open_event = db.scalars(
                select(AlertEvent).where(AlertEvent.rule_id == rule.id, AlertEvent.resolved_at.is_(None))
            ).first()
            if not rule.enabled:
                self._breach_since.pop(rule.id, None)
                if open_event:
                    open_event.resolved_at = now
                continue

            value = self.metric_value(db, rule, occ, queues)
            if value > rule.threshold:
                since = self._breach_since.setdefault(rule.id, now)
                if open_event:
                    open_event.peak_value = max(open_event.peak_value, value)
                elif (now - since).total_seconds() >= rule.min_duration_sec:
                    message = self.describe(db, rule, value)
                    db.add(
                        AlertEvent(
                            rule_id=rule.id, rule_name=rule.name, started_at=now, peak_value=value, message=message
                        )
                    )
                    if rule.notify:
                        send_notification("⚠️ " + message)
            elif value <= rule.threshold * 0.9:
                self._breach_since.pop(rule.id, None)
                if open_event:
                    open_event.resolved_at = now
                    if rule.notify:
                        send_notification(f"✅ Восстановлено: {rule.name}")
        db.commit()


async def run_alert_engine(interval: float = 5.0) -> None:
    engine = AlertEngine()

    def _tick() -> None:
        with SessionLocal() as db:
            engine.tick(db)

    while True:
        try:
            await asyncio.to_thread(_tick)
        except Exception:
            log.exception("alert tick failed")
        await asyncio.sleep(interval)
