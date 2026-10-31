import { useMemo, useState } from "react";
import { type Camera, type Floor, type Line, type Pt, type Zone, api } from "../api";
import { applyHomography, solveHomography } from "../lib/homography";
import Stage from "./Stage";
import { ErrorBox, Segmented } from "./ui";

type Tool = "select" | "line" | "zone";
type Sel = { kind: "line" | "zone"; index: number } | null;
type Drag = { kind: "line" | "zone"; index: number; point: number } | null;

const dist = (a: Pt, b: Pt) => Math.hypot(a[0] - b[0], a[1] - b[1]);

function LayoutTab({ camera, floors, onSaved }: { camera: Camera; floors: Floor[]; onSaved: () => void }) {
  const [lines, setLines] = useState<Line[]>(camera.lines);
  const [zones, setZones] = useState<Zone[]>(camera.zones);
  const [tool, setTool] = useState<Tool>("select");
  const [draft, setDraft] = useState<Pt[]>([]);
  const [sel, setSel] = useState<Sel>(null);
  const [drag, setDrag] = useState<Drag>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const touch = () => setSaved(false);
  const floorOptions = (
    <>
      <option value="">Улица</option>
      {floors.map((f) => (
        <option key={f.id} value={f.id}>{f.name}</option>
      ))}
    </>
  );

  function finishZone(points: Pt[]) {
    if (points.length < 3) return;
    setZones((z) => [...z, { name: `Очередь ${z.length + 1}`, kind: "queue", polygon: points, floor_id: camera.floor_id, min_dwell_sec: 5 }]);
    setSel({ kind: "zone", index: zones.length });
    setDraft([]);
    setTool("select");
    touch();
  }

  function onDown(p: Pt) {
    if (tool === "line") {
      if (draft.length === 0) return setDraft([p]);
      setLines((l) => [...l, { name: `Линия ${l.length + 1}`, p1: draft[0], p2: p, in_side: 1, floor_in_id: camera.floor_id, floor_out_id: null }]);
      setSel({ kind: "line", index: lines.length });
      setDraft([]);
      setTool("select");
      touch();
    } else if (tool === "zone") {
      if (draft.length >= 3 && dist(p, draft[0]) < 0.03) return finishZone(draft);
      setDraft((d) => [...d, p]);
    } else {
      setSel(null);
    }
  }

  function onMove(p: Pt) {
    if (!drag) return;
    touch();
    if (drag.kind === "line") {
      setLines((ls) => ls.map((l, i) => (i === drag.index ? { ...l, [drag.point === 0 ? "p1" : "p2"]: p } : l)));
    } else {
      setZones((zs) => zs.map((z, i) => (i === drag.index ? { ...z, polygon: z.polygon.map((q, k) => (k === drag.point ? p : q)) } : z)));
    }
  }

  async function save() {
    setError(null);
    try {
      await api(`/api/cameras/${camera.id}/layout`, { method: "PUT", json: { lines, zones } });
      setSaved(true);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  const patchLine = (i: number, patch: Partial<Line>) => { setLines((ls) => ls.map((l, k) => (k === i ? { ...l, ...patch } : l))); touch(); };
  const patchZone = (i: number, patch: Partial<Zone>) => { setZones((zs) => zs.map((z, k) => (k === i ? { ...z, ...patch } : z))); touch(); };

  return (
    <div className="editor">
      <div>
        <div className="toolbar" style={{ marginBottom: 10 }}>
          <Segmented<Tool>
            value={tool}
            onChange={(t) => { setTool(t); setDraft([]); }}
            options={[
              { value: "select", label: "Выбор и правка" },
              { value: "line", label: "＋ Линия подсчёта" },
              { value: "zone", label: "＋ Зона / очередь" },
            ]}
          />
          {tool === "zone" && draft.length >= 3 && <button className="btn sm primary" onClick={() => finishZone(draft)}>Замкнуть зону</button>}
          <span className="muted">
            {tool === "line" && (draft.length ? "Кликните вторую точку линии" : "Кликните первую точку линии")}
            {tool === "zone" && "Кликайте по углам зоны; клик у первой точки или кнопка замкнёт её"}
            {tool === "select" && "Перетаскивайте точки; стрелка показывает направление «внутрь»"}
          </span>
        </div>
        <Stage
          src={camera.has_snapshot ? `/api/cameras/${camera.id}/snapshot?t=${Date.now()}` : undefined}
          emptyHint="Снимка с камеры пока нет — worker загрузит его после запуска. Рисовать можно и так."
          cursor={tool === "select" ? "default" : "crosshair"}
          onDown={onDown}
          onMove={onMove}
          onUp={() => setDrag(null)}
        >
          {(w, h) => {
            const px = (p: Pt): Pt => [p[0] * w, p[1] * h];
            return (
              <>
                <defs>
                  <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path d="M0,0 L10,5 L0,10 z" fill="#22c55e" />
                  </marker>
                </defs>
                {zones.map((z, i) => {
                  const pts = z.polygon.map(px);
                  const active = sel?.kind === "zone" && sel.index === i;
                  const color = z.kind === "queue" ? "#f59e0b" : "#a855f7";
                  const cx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
                  const cy = pts.reduce((s, p) => s + p[1], 0) / pts.length;
                  return (
                    <g key={`z${i}`}>
                      <polygon points={pts.map((p) => p.join(",")).join(" ")} fill={color} fillOpacity={active ? 0.3 : 0.18} stroke={color} strokeWidth={active ? 3 : 2}
                        onPointerDown={(e) => { if (tool === "select") { e.stopPropagation(); setSel({ kind: "zone", index: i }); } }} />
                      <text x={cx} y={cy} textAnchor="middle" fill="#fff" fontSize={22} style={{ paintOrder: "stroke", stroke: "#000a", strokeWidth: 4 }}>{z.name}</text>
                      {tool === "select" && pts.map((p, k) => (
                        <circle key={k} cx={p[0]} cy={p[1]} r={9} fill="#fff" stroke={color} strokeWidth={3} style={{ cursor: "grab" }}
                          onPointerDown={(e) => { e.stopPropagation(); setSel({ kind: "zone", index: i }); setDrag({ kind: "zone", index: i, point: k }); }} />
                      ))}
                    </g>
                  );
                })}
                {lines.map((l, i) => {
                  const a = px(l.p1), b = px(l.p2);
                  const active = sel?.kind === "line" && sel.index === i;
                  const mid: Pt = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
                  const dx = b[0] - a[0], dy = b[1] - a[1];
                  const len = Math.hypot(dx, dy) || 1;
                  const n: Pt = [(-dy / len) * l.in_side, (dx / len) * l.in_side];
                  return (
                    <g key={`l${i}`}>
                      <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke="#3b82f6" strokeWidth={active ? 6 : 4} strokeLinecap="round"
                        onPointerDown={(e) => { if (tool === "select") { e.stopPropagation(); setSel({ kind: "line", index: i }); } }} />
                      <line x1={mid[0]} y1={mid[1]} x2={mid[0] + n[0] * 60} y2={mid[1] + n[1] * 60} stroke="#22c55e" strokeWidth={4} markerEnd="url(#arrow)" />
                      <text x={mid[0] + n[0] * 78} y={mid[1] + n[1] * 78 + 6} textAnchor="middle" fill="#22c55e" fontSize={20} fontWeight={700} style={{ paintOrder: "stroke", stroke: "#000a", strokeWidth: 4 }}>
                        внутрь
                      </text>
                      {tool === "select" && [a, b].map((p, k) => (
                        <circle key={k} cx={p[0]} cy={p[1]} r={9} fill="#fff" stroke="#3b82f6" strokeWidth={3} style={{ cursor: "grab" }}
                          onPointerDown={(e) => { e.stopPropagation(); setSel({ kind: "line", index: i }); setDrag({ kind: "line", index: i, point: k }); }} />
                      ))}
                    </g>
                  );
                })}
                {draft.length > 0 && (
                  <g>
                    <polyline points={draft.map((p) => px(p).join(",")).join(" ")} fill="none" stroke="#fff" strokeWidth={3} strokeDasharray="8 6" />
                    {draft.map((p, k) => <circle key={k} cx={px(p)[0]} cy={px(p)[1]} r={7} fill="#fff" />)}
                  </g>
                )}
              </>
            );
          }}
        </Stage>
        <ErrorBox message={error} />
        <div className="toolbar mt">
          <button className="btn primary" onClick={save}>Сохранить разметку</button>
          {saved && <span style={{ color: "var(--ok)" }}>Сохранено — worker подхватит изменения в течение 30 секунд</span>}
        </div>
      </div>

      <div>
        {lines.length + zones.length === 0 && <div className="muted">Добавьте линию подсчёта (входы, эскалаторы) или зону очереди.</div>}
        {lines.map((l, i) => (
          <div key={`li${i}`} className={`item ${sel?.kind === "line" && sel.index === i ? "sel" : ""}`} onClick={() => setSel({ kind: "line", index: i })}>
            <div style={{ display: "flex", gap: 6 }}>
              <input type="text" style={{ flex: 1 }} value={l.name} onChange={(e) => patchLine(i, { name: e.target.value })} />
              <button className="btn sm danger" onClick={() => { setLines(lines.filter((_, k) => k !== i)); setSel(null); touch(); }}>✕</button>
            </div>
            <label className="field">Люди, пересекающие линию в сторону стрелки, попадают на этаж
              <select value={l.floor_in_id ?? ""} onChange={(e) => patchLine(i, { floor_in_id: e.target.value ? Number(e.target.value) : null })}>{floorOptions}</select>
            </label>
            <label className="field">…и приходят из
              <select value={l.floor_out_id ?? ""} onChange={(e) => patchLine(i, { floor_out_id: e.target.value ? Number(e.target.value) : null })}>{floorOptions}</select>
            </label>
            <button className="btn sm" onClick={() => patchLine(i, { in_side: l.in_side === 1 ? -1 : 1 })}>⇄ Развернуть направление</button>
          </div>
        ))}
        {zones.map((z, i) => (
          <div key={`zo${i}`} className={`item ${sel?.kind === "zone" && sel.index === i ? "sel" : ""}`} onClick={() => setSel({ kind: "zone", index: i })}>
            <div style={{ display: "flex", gap: 6 }}>
              <input type="text" style={{ flex: 1 }} value={z.name} onChange={(e) => patchZone(i, { name: e.target.value })} />
              <button className="btn sm danger" onClick={() => { setZones(zones.filter((_, k) => k !== i)); setSel(null); touch(); }}>✕</button>
            </div>
            <label className="field">Тип
              <select value={z.kind} onChange={(e) => patchZone(i, { kind: e.target.value as Zone["kind"] })}>
                <option value="queue">Очередь</option>
                <option value="area">Область</option>
              </select>
            </label>
            <label className="field">Этаж
              <select value={z.floor_id ?? ""} onChange={(e) => patchZone(i, { floor_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">—</option>
                {floors.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </label>
            {z.kind === "queue" && (
              <label className="field">Считать в очереди тех, кто стоит дольше (сек)
                <input type="number" min={0} value={z.min_dwell_sec} onChange={(e) => patchZone(i, { min_dwell_sec: Number(e.target.value) })} />
              </label>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function CalibrationTab({ camera, floors, onSaved }: { camera: Camera; floors: Floor[]; onSaved: () => void }) {
  const floor = floors.find((f) => f.id === camera.floor_id);
  const [imgPts, setImgPts] = useState<Pt[]>([]);
  const [planPts, setPlanPts] = useState<Pt[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const computed = useMemo(() => (imgPts.length === 4 && planPts.length === 4 ? solveHomography(imgPts, planPts) : null), [imgPts, planPts]);
  const matrix = computed ?? camera.homography;
  const footprint = useMemo(
    () => (matrix ? ([[0, 0], [1, 0], [1, 1], [0, 1]] as Pt[]).map((p) => applyHomography(matrix, p)) : null),
    [matrix],
  );

  async function persist(h: number[][] | null) {
    setError(null);
    try {
      await api(`/api/cameras/${camera.id}`, {
        method: "PUT",
        json: { name: camera.name, rtsp_url: camera.rtsp_url, floor_id: camera.floor_id, enabled: camera.enabled, homography: h },
      });
      setSaved(true);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!floor || !floor.has_plan) {
    return <div className="empty">Для привязки нужен этаж камеры с загруженным планом. Укажите этаж в свойствах камеры и загрузите план в «Настройках».</div>;
  }

  const markers = (pts: Pt[], color: string) => (w: number, h: number) => (
    <>
      {pts.map((p, i) => (
        <g key={i}>
          <circle cx={p[0] * w} cy={p[1] * h} r={13} fill={color} stroke="#fff" strokeWidth={3} />
          <text x={p[0] * w} y={p[1] * h + 6} textAnchor="middle" fill="#fff" fontSize={16} fontWeight={700}>{i + 1}</text>
        </g>
      ))}
    </>
  );

  return (
    <div>
      <p className="muted" style={{ marginTop: 0 }}>
        Отметьте <b>4 точки на полу</b> на кадре камеры, затем <b>те же 4 точки в том же порядке</b> на плане (углы плитки, колонны, края коридора).
        Точки не должны лежать на одной прямой. Это нужно только для тепловой карты.
      </p>
      <div className="grid cols-2">
        <div>
          <b>1. Кадр камеры ({imgPts.length}/4)</b>
          <Stage
            src={camera.has_snapshot ? `/api/cameras/${camera.id}/snapshot?t=${Date.now()}` : undefined}
            emptyHint="Нет снимка с камеры"
            cursor={imgPts.length < 4 ? "crosshair" : "default"}
            onDown={(p) => { setSaved(false); setImgPts((a) => (a.length < 4 ? [...a, p] : a)); }}
          >
            {markers(imgPts, "#3b82f6")}
          </Stage>
        </div>
        <div>
          <b>2. План: {floor.name} ({planPts.length}/4)</b>
          <Stage
            src={`/api/floors/${floor.id}/plan`}
            cursor={planPts.length < 4 ? "crosshair" : "default"}
            onDown={(p) => { setSaved(false); setPlanPts((a) => (a.length < 4 ? [...a, p] : a)); }}
          >
            {(w, h) => (
              <>
                {footprint && (
                  <polygon points={footprint.map((p) => `${p[0] * w},${p[1] * h}`).join(" ")} fill="#3b82f6" fillOpacity={0.2} stroke="#3b82f6" strokeWidth={3} strokeDasharray="8 5" />
                )}
                {markers(planPts, "#f59e0b")(w, h)}
              </>
            )}
          </Stage>
        </div>
      </div>
      <ErrorBox message={error} />
      {imgPts.length === 4 && planPts.length === 4 && !computed && <div className="error mt">Точки лежат на одной прямой — выберите другие.</div>}
      <div className="toolbar mt">
        <button className="btn primary" disabled={!computed} onClick={() => persist(computed)}>Сохранить привязку</button>
        <button className="btn" onClick={() => { setImgPts([]); setPlanPts([]); setSaved(false); }}>Сбросить точки</button>
        {camera.homography && <button className="btn danger" onClick={() => persist(null)}>Удалить привязку</button>}
        {footprint && <span className="muted">Синяя область на плане — то, что видит камера.</span>}
        {saved && <span style={{ color: "var(--ok)" }}>Сохранено</span>}
      </div>
    </div>
  );
}

export default function CameraEditor({ camera, floors, onSaved }: { camera: Camera; floors: Floor[]; onSaved: () => void }) {
  const [tab, setTab] = useState<"layout" | "calib">("layout");
  return (
    <>
      <div style={{ marginBottom: 14 }}>
        <Segmented
          value={tab}
          onChange={setTab}
          options={[
            { value: "layout", label: "Линии и зоны" },
            { value: "calib", label: "Привязка к плану" },
          ]}
        />
      </div>
      {tab === "layout" ? <LayoutTab camera={camera} floors={floors} onSaved={onSaved} /> : <CalibrationTab camera={camera} floors={floors} onSaved={onSaved} />}
    </>
  );
}
