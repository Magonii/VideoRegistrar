import { useEffect, useMemo, useRef, useState } from "react";
import { type Floor, type Heatmap as HeatmapData, qs } from "../api";
import { ErrorBox, PageHead, Segmented } from "../components/ui";
import { useApi } from "../hooks";
import { addDays, dateInputValue, fmtNum } from "../lib/format";

const RAMP: [number, [number, number, number]][] = [
  [0, [0, 0, 255]],
  [0.25, [0, 229, 255]],
  [0.5, [61, 220, 75]],
  [0.75, [255, 230, 0]],
  [1, [255, 26, 26]],
];

function ramp(t: number): [number, number, number] {
  for (let i = 1; i < RAMP.length; i++) {
    if (t <= RAMP[i][0]) {
      const [t0, c0] = RAMP[i - 1];
      const [t1, c1] = RAMP[i];
      const k = (t - t0) / (t1 - t0);
      return [c0[0] + (c1[0] - c0[0]) * k, c0[1] + (c1[1] - c0[1]) * k, c0[2] + (c1[2] - c0[2]) * k];
    }
  }
  return RAMP[RAMP.length - 1][1];
}

/** Сначала рисуем размытые пятна в канал прозрачности, затем красим по таблице «синий → красный». */
function drawHeat(canvas: HTMLCanvasElement, h: HeatmapData, gain: number) {
  const scale = 8;
  const W = h.cols * scale;
  const H = h.rows * scale;
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d")!;
  ctx.clearRect(0, 0, W, H);
  if (h.max === 0) return;

  const off = document.createElement("canvas");
  off.width = W;
  off.height = H;
  const o = off.getContext("2d")!;
  const r = scale * 2.6;
  h.cells.forEach((n, i) => {
    if (!n) return;
    const cx = (i % h.cols) * scale + scale / 2;
    const cy = Math.floor(i / h.cols) * scale + scale / 2;
    const a = Math.min(1, Math.pow(n / h.max, 0.65) * gain * 0.6);
    const g = o.createRadialGradient(cx, cy, 0, cx, cy, r);
    g.addColorStop(0, `rgba(0,0,0,${a})`);
    g.addColorStop(1, "rgba(0,0,0,0)");
    o.fillStyle = g;
    o.fillRect(cx - r, cy - r, r * 2, r * 2);
  });

  const img = o.getImageData(0, 0, W, H);
  const d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3];
    if (a < 4) {
      d[i + 3] = 0;
      continue;
    }
    const [rr, gg, bb] = ramp(a / 255);
    d[i] = rr;
    d[i + 1] = gg;
    d[i + 2] = bb;
    d[i + 3] = Math.min(235, a * 1.15);
  }
  ctx.putImageData(img, 0, 0);
}

type Mode = "day" | "7d";

export default function Heatmap() {
  const { data: floors } = useApi<Floor[]>("/api/floors");
  const [floorId, setFloorId] = useState<number | null>(null);
  const [mode, setMode] = useState<Mode>("day");
  const [date, setDate] = useState(dateInputValue(new Date()));
  const [hour, setHour] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [gain, setGain] = useState(1.4);
  const [aspect, setAspect] = useState(1.6);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (floorId === null && floors?.length) setFloorId(floors[0].id);
  }, [floors, floorId]);

  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => setHour((h) => ((h ?? -1) + 1) % 24), 1400);
    return () => clearInterval(t);
  }, [playing]);

  const query = useMemo(() => {
    if (floorId === null) return null;
    const day = new Date(`${date}T00:00:00`);
    let from: Date;
    let to: Date;
    if (mode === "7d") {
      to = addDays(new Date(`${dateInputValue(new Date())}T00:00:00`), 1);
      from = addDays(to, -7);
    } else if (hour === null) {
      from = day;
      to = addDays(day, 1);
    } else {
      from = new Date(day.getTime() + hour * 3_600_000);
      to = new Date(from.getTime() + 3_600_000);
    }
    // ячейки сетки примерно квадратные при любых пропорциях плана
    const cols = 96;
    const rows = Math.max(8, Math.min(200, Math.round(cols / aspect)));
    return `/api/heatmap?${qs({ floor_id: floorId, from: from.toISOString(), to: to.toISOString(), cols, rows })}`;
  }, [floorId, mode, date, hour, aspect]);

  const { data, error } = useApi<HeatmapData>(query);

  useEffect(() => {
    if (canvasRef.current && data) drawHeat(canvasRef.current, data, gain);
  }, [data, gain]);

  const floor = floors?.find((f) => f.id === floorId);

  return (
    <>
      <PageHead title="Тепловая карта">
        <Segmented<Mode>
          value={mode}
          onChange={(m) => {
            setMode(m);
            setPlaying(false);
          }}
          options={[
            { value: "day", label: "День" },
            { value: "7d", label: "7 дней" },
          ]}
        />
        {mode === "day" && <input type="date" value={date} max={dateInputValue(new Date())} onChange={(e) => setDate(e.target.value)} />}
      </PageHead>
      <ErrorBox message={error} />

      <div className="toolbar" style={{ marginBottom: 14 }}>
        <Segmented
          value={String(floorId ?? "")}
          onChange={(v) => setFloorId(Number(v))}
          options={(floors ?? []).map((f) => ({ value: String(f.id), label: f.name }))}
        />
        <span className="muted">{data ? `${fmtNum(data.total)} точек треков` : ""}</span>
      </div>

      <div className="card">
        <div className="plan-wrap" style={{ aspectRatio: String(aspect) }}>
          {floor?.has_plan && (
            <img
              src={`/api/floors/${floor.id}/plan`}
              alt={`План: ${floor.name}`}
              onLoad={(e) => e.currentTarget.naturalWidth && setAspect(e.currentTarget.naturalWidth / e.currentTarget.naturalHeight)}
            />
          )}
          <canvas ref={canvasRef} />
          {data && data.total === 0 && (
            <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", color: "#6b7686" }}>
              За выбранный период нет данных по этому этажу
            </div>
          )}
        </div>

        {mode === "day" && (
          <div style={{ marginTop: 16, display: "grid", gap: 10 }}>
            <div className="toolbar">
              <button className="btn primary sm" onClick={() => { if (!playing && hour === null) setHour(0); setPlaying(!playing); }}>
                {playing ? "⏸ Пауза" : "▶ Воспроизвести по часам"}
              </button>
              <button className={`btn sm ${hour === null ? "primary" : ""}`} onClick={() => { setHour(null); setPlaying(false); }}>
                Весь день
              </button>
              <b>{hour === null ? "Весь день" : `${String(hour).padStart(2, "0")}:00 – ${String((hour + 1) % 24).padStart(2, "0")}:00`}</b>
            </div>
            <input
              className="slider"
              type="range"
              min={0}
              max={23}
              value={hour ?? 0}
              onChange={(e) => {
                setHour(Number(e.target.value));
                setPlaying(false);
              }}
            />
          </div>
        )}

        <div className="toolbar" style={{ marginTop: 14, justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, width: 320 }}>
            <span className="muted">меньше</span>
            <div className="legend" style={{ flex: 1 }} />
            <span className="muted">больше</span>
          </div>
          <label className="check muted">
            Контраст
            <input type="range" min={0.5} max={3} step={0.1} value={gain} onChange={(e) => setGain(Number(e.target.value))} />
          </label>
        </div>
      </div>
    </>
  );
}
