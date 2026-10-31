"""Анализаторы подписаны на общий поток треков камеры: {track_id: (x, y)} в координатах 0..1,
где (x, y) — точка у ног человека (середина нижней грани рамки)."""
from dataclasses import dataclass, field

from .geometry import Point, apply_homography, crossing_direction, point_in_polygon


class LineCounter:
    """Счёт пересечений линий. Событие рождается на шаге трека prev->cur, пересёкшем отрезок."""

    def __init__(self, lines: list[dict]) -> None:
        self.lines = lines
        self._prev: dict[int, Point] = {}

    def update(self, points: dict[int, Point]) -> list[dict]:
        events = []
        for tid, cur in points.items():
            prev = self._prev.get(tid)
            if prev is not None:
                for line in self.lines:
                    d = crossing_direction(tuple(line["p1"]), tuple(line["p2"]), line["in_side"], prev, cur)
                    if d:
                        events.append({"line_id": line["id"], "direction": d, "count": 1})
            self._prev[tid] = cur
        # забываем исчезнувшие треки
        for tid in [t for t in self._prev if t not in points]:
            del self._prev[tid]
        return events


@dataclass
class _QueueState:
    zone: dict
    entered_at: dict[int, float] = field(default_factory=dict)
    last_emit: float = 0.0


class QueueMonitor:
    """Очередь = люди в зоне, пробывшие там не меньше min_dwell_sec (отсекает проходящих мимо).
    Ожидание = время самого давно стоящего. Снимок отправляется раз в emit_every секунд."""

    def __init__(self, zones: list[dict], emit_every: float = 5.0) -> None:
        self.states = [_QueueState(z) for z in zones if z.get("kind") == "queue"]
        self.emit_every = emit_every

    def update(self, points: dict[int, Point], now: float) -> list[dict]:
        snapshots = []
        for st in self.states:
            inside = {t for t, p in points.items() if point_in_polygon(st.zone["polygon"], p)}
            for t in inside:
                st.entered_at.setdefault(t, now)
            for t in [t for t in st.entered_at if t not in inside]:
                del st.entered_at[t]

            if now - st.last_emit < self.emit_every:
                continue
            st.last_emit = now
            dwell = [now - st.entered_at[t] for t in inside]
            min_dwell = st.zone.get("min_dwell_sec", 5)
            queued = [d for d in dwell if d >= min_dwell]
            snapshots.append(
                {"zone_id": st.zone["id"], "people": len(queued), "max_wait_sec": round(max(queued, default=0.0), 1)}
            )
        return snapshots


class TrackSampler:
    """Раз в `period` секунд на трек фиксирует точку в координатах плана этажа (для хитмапа).
    Без матрицы гомографии не работает: хитмап строится только по откалиброванным камерам."""

    def __init__(self, homography: list[list[float]] | None, period: float = 0.5) -> None:
        self.h = homography
        self.period = period
        self._last: dict[int, float] = {}

    def update(self, points: dict[int, Point], now: float) -> list[dict]:
        if not self.h:
            return []
        out = []
        for tid, p in points.items():
            if now - self._last.get(tid, 0.0) >= self.period:
                self._last[tid] = now
                x, y = apply_homography(self.h, p)
                if 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                    out.append({"track_id": tid, "x": round(x, 4), "y": round(y, 4)})
        for tid in [t for t in self._last if t not in points]:
            del self._last[tid]
        return out
