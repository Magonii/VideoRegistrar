import asyncio
import contextlib
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import DEMO, LAB_DIR
from .db import SessionLocal, init_db
from .routers import analytics, config_api, ingest
from .services.alerts import run_alert_engine
from .services.overview import build_overview

log = logging.getLogger("app")


class Broadcaster:
    """Раз в interval секунд рассылает сводку всем подключённым WebSocket-клиентам."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def run(self, interval: float = 2.0) -> None:
        def _build() -> dict:
            with SessionLocal() as db:
                return build_overview(db)

        while True:
            await asyncio.sleep(interval)
            if not self.clients:
                continue
            try:
                payload = await asyncio.to_thread(_build)
            except Exception:
                log.exception("overview build failed")
                continue
            for ws in list(self.clients):
                try:
                    await ws.send_json(payload)
                except Exception:
                    self.clients.discard(ws)


broadcaster = Broadcaster()


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    tasks = [asyncio.create_task(run_alert_engine()), asyncio.create_task(broadcaster.run())]
    if DEMO:
        from .demo import run_demo

        tasks.append(asyncio.create_task(run_demo()))
    yield
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="VideoRegistrar — аналитика посетителей ТЦ", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(config_api.router)
app.include_router(ingest.router)
app.include_router(analytics.router)


@app.get("/api/health")
def health():
    return {"ok": True, "demo": DEMO}


@app.get("/api/lab/status")
def lab_status():
    """Есть ли результаты эксперимента с несколькими камерами и какие видео готовы."""
    videos = sorted(p.name for p in LAB_DIR.glob("*.mp4")) if LAB_DIR.exists() else []
    return {"available": (LAB_DIR / "lab.json").exists(), "videos": videos}


# Видео и lab.json; StaticFiles поддерживает Range-запросы, поэтому перемотка в браузере работает.
app.mount("/api/lab/files", StaticFiles(directory=LAB_DIR, check_dir=False), name="lab-files")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    broadcaster.clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # клиент ничего не шлёт; ждём разрыва соединения
    except WebSocketDisconnect:
        pass
    finally:
        broadcaster.clients.discard(ws)
