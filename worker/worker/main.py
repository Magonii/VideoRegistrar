"""Vision-worker одной камеры: YOLO + ByteTrack -> линии, очереди, точки для хитмапа -> backend.

Запуск:
  python -m worker --camera-id 1 --backend http://localhost:8000
  python -m worker --camera-id 1 --source test.mp4        # прогон по видеофайлу
"""
import argparse
import logging
import time

from .analyzers import LineCounter, QueueMonitor, TrackSampler
from .client import BackendClient

log = logging.getLogger("worker")

SNAPSHOT_EVERY = 60.0
CONFIG_REFRESH_EVERY = 30.0


def build_analyzers(cam: dict):
    return (
        LineCounter(cam["lines"]),
        QueueMonitor(cam["zones"]),
        TrackSampler(cam.get("homography")),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera-id", type=int, required=True)
    ap.add_argument("--backend", default="http://localhost:8000")
    ap.add_argument("--source", help="RTSP-адрес или видеофайл (по умолчанию rtsp_url камеры из backend)")
    ap.add_argument("--model", default="yolo11n.pt")
    ap.add_argument("--device", default=None, help="например 0 для GPU или cpu")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=960)
    ap.add_argument("--vid-stride", type=int, default=1, help="брать каждый N-й кадр, чтобы снизить нагрузку")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from ultralytics import YOLO  # импорт здесь, чтобы геометрия и тесты не требовали torch
    import cv2

    client = BackendClient(args.backend, args.camera_id)
    cam = client.get_camera()
    source = args.source or cam["rtsp_url"]
    if not source:
        raise SystemExit("Не задан источник видео: укажите --source или rtsp_url камеры в интерфейсе")
    log.info("камера %s (%s), источник: %s", cam["name"], args.camera_id, source)

    model = YOLO(args.model)
    lines, queues, sampler = build_analyzers(cam)
    last_cfg = last_snap = 0.0

    while True:  # переподключение при обрыве потока
        try:
            stream = model.track(
                source=source, stream=True, persist=True, classes=[0], conf=args.conf, imgsz=args.imgsz,
                tracker="bytetrack.yaml", device=args.device, vid_stride=args.vid_stride, verbose=False,
            )
            for result in stream:
                now = time.time()
                h, w = result.orig_shape
                points: dict[int, tuple[float, float]] = {}
                boxes = result.boxes
                if boxes is not None and boxes.id is not None:
                    for (x1, y1, x2, y2), tid in zip(boxes.xyxy.cpu().numpy(), boxes.id.int().cpu().tolist()):
                        points[tid] = (float((x1 + x2) / 2 / w), float(y2 / h))  # точка у ног

                client.add("crossings", lines.update(points))
                client.add("queues", queues.update(points, now))
                client.add("tracks", sampler.update(points, now))
                client.maybe_flush()

                if now - last_snap >= SNAPSHOT_EVERY:
                    ok, jpg = cv2.imencode(".jpg", result.orig_img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    if ok:
                        client.upload_snapshot(jpg.tobytes())
                    last_snap = now

                if now - last_cfg >= CONFIG_REFRESH_EVERY:  # подхватываем правки линий и зон без перезапуска
                    last_cfg = now
                    try:
                        cam = client.get_camera()
                        lines, queues, sampler = build_analyzers(cam)
                    except Exception as exc:
                        log.warning("конфиг не обновлён: %s", exc)
            if args.source and not args.source.startswith("rtsp"):
                log.info("видеофайл закончился")
                client.flush()
                return
        except KeyboardInterrupt:
            client.flush()
            return
        except Exception:
            log.exception("поток оборвался, переподключение через 5 с")
            time.sleep(5)


if __name__ == "__main__":
    main()
