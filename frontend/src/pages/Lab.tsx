import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Chart, { COLORS } from "../components/Chart";
import { ErrorBox, Kpi, PageHead, Segmented } from "../components/ui";
import { useApi } from "../hooks";
import {
  COLOR_IN,
  COLOR_OUT,
  type DrawOptions,
  type LabData,
  drawCameraView,
  drawGround,
  groundAspect,
  groundView,
  heatPointsAllTime,
  heatPointsWindow,
  renderHeat,
} from "../lib/labDraw";

type HeatMode = "off" | "all" | "30s";
type Rate = "0.5" | "1" | "2";

const FILES = "/api/lab/files";

const fmtT = (t: number) => {
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
};

export default function Lab() {
  const { data: status } = useApi<{ available: boolean; videos: string[] }>("/api/lab/status");
  const hasMosaic = status?.videos.includes("mosaic.mp4") ?? false;
  const [data, setData] = useState<LabData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState<Rate>("1");
  const [time, setTime] = useState(0); // для интерфейса, обновляется ~5 раз в секунду
  const [focus, setFocus] = useState<number | null>(null);
  const [opt, setOpt] = useState<DrawOptions>({ boxes: true, ids: true, territory: true });
  const [heatMode, setHeatMode] = useState<HeatMode>("30s");
  const [waiting, setWaiting] = useState(false);

  const clock = useRef(0);
  const video = useRef<HTMLVideoElement | null>(null); // все 7 камер в одном видео — синхронно по построению
  const overlays = useRef<(HTMLCanvasElement | null)[]>([]);
  const ground = useRef<HTMLCanvasElement | null>(null);
  const live = useRef({ playing, rate: Number(rate), opt, heatMode });
  live.current = { playing, rate: Number(rate), opt, heatMode };

  useEffect(() => {
    if (!status?.available) return;
    fetch(`${FILES}/lab.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`lab.json: HTTP ${r.status}`))))
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [status?.available]);

  const view = useMemo(() => (data ? groundView(data) : null), [data]);

  const seek = useCallback(
    (t: number) => {
      if (!data) return;
      const v = Math.max(0, Math.min(data.duration - 0.05, t));
      clock.current = v;
      if (video.current) video.current.currentTime = v;
      setTime(v);
    },
    [data],
  );

  // Один цикл на всё: ведёт общий таймер, держит видео в синхроне и рисует наложения.
  useEffect(() => {
    if (!data || !view) return;
    let raf = 0;
    let last = performance.now();
    let lastUi = 0;
    let heatCanvas: HTMLCanvasElement | null = null;
    let heatKey = "";

    const frame = (now: number) => {
      const dt = (now - last) / 1000;
      last = now;
      const { playing: isPlaying, rate: r, opt: o, heatMode: hm } = live.current;
      const el = video.current;
      const ready = !!el && el.readyState >= 2;
      if (el) {
        el.playbackRate = r;
        if (isPlaying && el.paused && !el.ended) void el.play().catch(() => undefined);
        if (!isPlaying && !el.paused) el.pause();
        if (el.ended) setPlaying(false);
        clock.current = el.currentTime;
      } else if (isPlaying) {
        clock.current = Math.min(data.duration, clock.current + dt * r); // видео нет — двигаем время сами
      }
      const t = clock.current;
      const stalled = isPlaying && !!el && el.readyState < 3;

      data.cameras.forEach((_, ci) => {
        const canvas = overlays.current[ci];
        if (canvas) drawCameraView(canvas, data, ci, t, o, ready ? el : null);
      });

      if (ground.current) {
        const W = ground.current.clientWidth;
        const H = ground.current.clientHeight;
        const key = hm === "30s" ? `30s:${Math.floor(t * 2)}:${W}` : `${hm}:${W}`;
        if (hm === "off") heatCanvas = null;
        else if (key !== heatKey && W > 0) {
          heatKey = key;
          heatCanvas = renderHeat(Math.round(W / 2), Math.round(H / 2), view,
            hm === "all" ? heatPointsAllTime(data) : heatPointsWindow(data, t, 30), 0.9);
        }
        drawGround(ground.current, data, view, t, heatCanvas, o.ids);
      }

      if (now - lastUi > 200) {
        lastUi = now;
        setTime(t);
        setWaiting(stalled);
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [data, view]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLSelectElement) return;
      if (e.code === "Space") {
        e.preventDefault();
        setPlaying((p) => !p);
      } else if (e.code === "ArrowRight") seek(clock.current + 5);
      else if (e.code === "ArrowLeft") seek(clock.current - 5);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [seek]);

  const chartOption = useMemo(() => {
    if (!data) return null;
    return {
      grid: { left: 44, right: 16, top: 36, bottom: 30 },
      tooltip: { trigger: "axis" as const },
      xAxis: { type: "value" as const, min: 0, max: data.duration, axisLabel: { formatter: (v: number) => fmtT(v).slice(0, -2) } },
      yAxis: { type: "value" as const, name: "людей в территории", nameTextStyle: { color: "#6b7686" } },
      series: [
        {
          name: "В территории",
          type: "line" as const,
          symbol: "none",
          color: COLORS.occupancy,
          areaStyle: { opacity: 0.12 },
          data: data.frames.map((f, k) => [k / data.fps, f.n]),
          markLine: { symbol: "none", animation: false, lineStyle: { color: "#d93a3a", width: 2 }, label: { show: false }, data: [{ xAxis: time }] },
        },
      ],
    };
  }, [data, time]);

  if (status && !status.available) {
    return (
      <>
        <PageHead title="Мультикамера" />
        <div className="card">
          Результатов эксперимента пока нет. Запустите в папке <code>lab</code>: <code>python export_web.py</code> (см. lab/README.md).
        </div>
      </>
    );
  }
  if (!data || !view) return <div className="empty">{error ?? "Загрузка данных…"}</div>;

  const k = Math.min(data.frames.length - 1, Math.floor(time * data.fps));
  const nNow = data.frames[k].n;
  const enters = data.events.filter((e) => e.kind === "enter" && e.t <= time).length;
  const exits = data.events.filter((e) => e.kind === "exit" && e.t <= time).length;
  const recent = data.events.filter((e) => e.t <= time).slice(-12).reverse();
  const s = data.summary;
  const acc = s.vs_dataset_labels?.territory;

  return (
    <>
      <PageHead title="Мультикамера: 7 камер, одна территория">
        <span className="muted">WILDTRACK · {data.ground.territory_m2} м² · {data.duration} с</span>
      </PageHead>
      <ErrorBox message={error} />

      <div className="card lab-controls">
        <button className="btn primary" onClick={() => setPlaying(!playing)} style={{ minWidth: 110 }}>
          {playing ? "⏸ Пауза" : "▶ Смотреть"}
        </button>
        <button className="btn sm" onClick={() => seek(clock.current - 5)}>−5 с</button>
        <button className="btn sm" onClick={() => seek(clock.current + 5)}>+5 с</button>
        <input className="slider" type="range" min={0} max={data.duration} step={0.1} value={time} onChange={(e) => seek(Number(e.target.value))} style={{ flex: 1, minWidth: 160 }} />
        <b style={{ fontVariantNumeric: "tabular-nums", minWidth: 120 }}>{fmtT(time)} / {fmtT(data.duration)}</b>
        <Segmented<Rate> value={rate} onChange={setRate} options={[{ value: "0.5", label: "0.5×" }, { value: "1", label: "1×" }, { value: "2", label: "2×" }]} />
        {waiting && <span className="muted">подгрузка видео…</span>}
      </div>

      <div className="toolbar" style={{ margin: "12px 0" }}>
        <label className="check"><input type="checkbox" checked={opt.boxes} onChange={(e) => setOpt({ ...opt, boxes: e.target.checked })} /> Рамки</label>
        <label className="check"><input type="checkbox" checked={opt.ids} onChange={(e) => setOpt({ ...opt, ids: e.target.checked })} /> Номера людей</label>
        <label className="check"><input type="checkbox" checked={opt.territory} onChange={(e) => setOpt({ ...opt, territory: e.target.checked })} /> Граница территории</label>
        <span className="muted" style={{ marginLeft: 8 }}>Тепловая карта:</span>
        <Segmented<HeatMode> value={heatMode} onChange={setHeatMode} options={[{ value: "off", label: "нет" }, { value: "30s", label: "последние 30 с" }, { value: "all", label: "за всё время" }]} />
        <span className="muted" style={{ marginLeft: "auto" }}>
          <span style={{ color: COLOR_IN }}>■</span> в территории <span style={{ color: COLOR_OUT, marginLeft: 8 }}>■</span> вне её
          <span style={{ marginLeft: 8 }}>□</span> не подтверждён · клик по камере — крупно · пробел — пауза
        </span>
      </div>

      <div className="grid cols-4">
        <Kpi label="Сейчас в территории" value={nNow} sub={`в среднем ${s.avg_people_in_territory}`} />
        <Kpi label="Зашли к этому моменту" value={enters} sub={`всего за запись ${s.events.enter}`} />
        <Kpi label="Вышли к этому моменту" value={exits} sub={`всего за запись ${s.events.exit}`} />
        <Kpi label="Точность (сверка с разметкой)" value={acc ? `±${acc.count_mae}` : "—"} sub={acc ? `чел. в кадре · F1 ${acc.f1} · позиция ${acc.pos_err_cm} см` : undefined} />
      </div>

      {/* Источник кадров для всех плиток; сам на странице не виден. */}
      <video ref={video} className="lab-source" src={`${FILES}/${data.mosaic.file}`} muted playsInline preload="auto" />
      {!hasMosaic && <div className="muted">видео ещё не готово</div>}

      <div className="cam-grid mt">
        {data.cameras.map((cam, ci) => (
          <div key={cam.id} className={`cam-tile ${focus === ci ? "focus" : ""}`} onClick={() => setFocus(focus === ci ? null : ci)}>
            <canvas ref={(el) => { overlays.current[ci] = el; }} />
            <span className="cam-label">{cam.name}</span>
          </div>
        ))}
        <div className="cam-tile info-tile">
          <div>
            <b>Синхронизация</b>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              Сдвиг каждой камеры найден автоматически и уже учтён:
            </div>
            <div style={{ fontSize: 12, marginTop: 6, lineHeight: 1.6 }}>
              {data.cameras.map((c) => (
                <span key={c.id} style={{ marginRight: 10, whiteSpace: "nowrap" }}>
                  {c.name}: +{(c.offset_frames / 60).toFixed(2)} с
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="card mt" style={{ padding: 12 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <h2 style={{ margin: 0 }}>Вид сверху</h2>
          <span className="muted">сетка 5 м · ▲ камеры · кольца — заходы и выходы</span>
        </div>
        <canvas ref={ground} className="ground-canvas" style={{ aspectRatio: String(groundAspect(view)) }} />
      </div>

      <div className="grid mt" style={{ gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)" }}>
        <div className="card">
          <h2>Людей в территории (клик по графику — перемотка)</h2>
          {chartOption && (
            <Chart
              height={240}
              option={chartOption}
              onEvents={{
                click: (p: unknown) => {
                  const v = (p as { value?: [number, number] }).value;
                  if (v) seek(v[0]);
                },
              }}
            />
          )}
        </div>
        <div className="card">
          <h2>Последние события</h2>
          {recent.length === 0 && <div className="muted">Пока никто не заходил и не выходил</div>}
          <table>
            <tbody>
              {recent.map((e, i) => (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => seek(e.t - 2)}>
                  <td style={{ fontVariantNumeric: "tabular-nums" }}>{fmtT(e.t)}</td>
                  <td><span className={`pill ${e.kind === "enter" ? "ok" : "warn"}`}>{e.kind === "enter" ? "зашёл" : "вышел"}</span></td>
                  <td className="muted">№ {e.track}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {s.events_dataset_labels && s.events_match && acc && (
        <div className="card mt">
          <h2>Насколько это точно (сверка с ручной разметкой датасета)</h2>
          <table>
            <tbody>
              <tr><td>Людей в территории в среднем</td><td>система <b>{s.avg_people_in_territory}</b></td><td>разметка <b>{s.avg_gt_in_territory}</b></td></tr>
              <tr><td>Ошибка числа людей в кадре</td><td colSpan={2}><b>±{acc.count_mae}</b> человека</td></tr>
              <tr><td>Найдено реальных людей / найденные реальны</td><td colSpan={2}><b>{Math.round(acc.recall * 100)}%</b> / <b>{Math.round(acc.precision * 100)}%</b> · ошибка позиции {acc.pos_err_cm} см</td></tr>
              <tr><td>Заходы / выходы</td><td>система <b>{s.events.enter} / {s.events.exit}</b></td><td>разметка <b>{s.events_dataset_labels.enter} / {s.events_dataset_labels.exit}</b></td></tr>
              <tr><td>Совпадение отдельных событий (±2 с, ±2 м)</td><td colSpan={2}><b>{Math.round(s.events_match.precision * 100)}%</b> наших верны, найдено <b>{Math.round(s.events_match.recall * 100)}%</b> настоящих</td></tr>
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
