import os
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'mall.db').as_posix()}")

# Часовой пояс ТЦ: границы дней, часовые корзины и «сброс заполняемости» считаются по нему.
MALL_TZ = ZoneInfo(os.getenv("MALL_TZ", "Asia/Almaty"))

# Демо-режим: генерирует историю за неделю и «живые» события, камеры не нужны.
DEMO = os.getenv("DEMO", "0") == "1"
DEMO_OPEN_HOUR = int(os.getenv("DEMO_OPEN_HOUR", "10"))
DEMO_CLOSE_HOUR = int(os.getenv("DEMO_CLOSE_HOUR", "22"))

# Результаты офлайн-эксперимента с несколькими камерами (lab/export_web.py): видео и lab.json.
LAB_DIR = Path(os.getenv("LAB_DIR", BASE_DIR.parent / "data" / "output" / "web"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Камера считается «в сети», если worker присылал данные не позже, чем N секунд назад.
CAMERA_ONLINE_SEC = 30
# Снимок очереди старше N секунд считается устаревшим.
QUEUE_STALE_SEC = 120
