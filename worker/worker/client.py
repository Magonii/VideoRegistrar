import logging
import threading
import time

import httpx

log = logging.getLogger("worker.client")

MAX_BUFFER = 50_000  # при долгой потере связи старые точки треков отбрасываем, события пересечений — нет


class BackendClient:
    """Копит события и отправляет пакетом раз в flush_every секунд. При ошибке сети данные остаются
    в буфере и уходят со следующей попыткой; пустой пакет служит heartbeat'ом камеры."""

    def __init__(self, base_url: str, camera_id: int, flush_every: float = 1.0) -> None:
        self.camera_id = camera_id
        self.http = httpx.Client(base_url=base_url, timeout=10)
        self.flush_every = flush_every
        self._lock = threading.Lock()
        self._buf: dict[str, list] = {"crossings": [], "queues": [], "tracks": []}
        self._last_flush = 0.0

    def add(self, kind: str, items: list[dict]) -> None:
        if not items:
            return
        with self._lock:
            self._buf[kind].extend(items)
            if len(self._buf["tracks"]) > MAX_BUFFER:
                del self._buf["tracks"][: len(self._buf["tracks"]) - MAX_BUFFER]

    def get_camera(self) -> dict:
        r = self.http.get(f"/api/cameras/{self.camera_id}")
        r.raise_for_status()
        return r.json()

    def maybe_flush(self) -> None:
        if time.time() - self._last_flush >= self.flush_every:
            self.flush()

    def flush(self) -> None:
        self._last_flush = time.time()
        with self._lock:
            payload = {"camera_id": self.camera_id, **self._buf}
            self._buf = {"crossings": [], "queues": [], "tracks": []}
        try:
            self.http.post("/api/ingest", json=payload).raise_for_status()
        except Exception as exc:
            log.warning("не удалось отправить пакет (%s), вернул в буфер", exc)
            with self._lock:
                for k in self._buf:
                    self._buf[k] = payload[k] + self._buf[k]

    def upload_snapshot(self, jpeg: bytes) -> None:
        try:
            self.http.post(
                f"/api/cameras/{self.camera_id}/snapshot", files={"file": ("snapshot.jpg", jpeg, "image/jpeg")}
            ).raise_for_status()
        except Exception as exc:
            log.warning("снимок не отправлен: %s", exc)
