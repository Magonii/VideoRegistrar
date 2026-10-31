/** Отрисовка для страницы «Мультикамера»: рамки поверх видео и вид сверху. Чистые функции над canvas. */

export type Box = [number, number, number, number, number, number]; // x1, y1, x2, y2, трек (-1), состояние (1/0/-1)
export type Person = [number, number, number, number]; // трек (-1), x м, y м, в территории 0/1

export interface LabData {
  fps: number;
  duration: number;
  video: { fps: number; width: number; height: number };
  /** Все камеры в одном видео: у каждой камеры своя плитка [x, y] размером tile_w × tile_h. */
  mosaic: { file: string; tile_w: number; tile_h: number; width: number; height: number; tiles: [number, number][] };
  source: { width: number; height: number };
  cameras: { id: number; name: string; offset_frames: number; territory: number[][][]; position: [number, number] }[];
  ground: { x_min: number; x_max: number; y_min: number; y_max: number; territory: number[][][]; territory_m2: number };
  frames: { n: number; p: Person[] }[];
  boxes: Box[][][]; // [камера][кадр][рамка]
  events: { t: number; kind: "enter" | "exit"; track: number; x: number; y: number }[];
  heat: { rows: number; cols: number; values: number[] };
  summary: LabSummary;
}

export interface LabSummary {
  territory_m2: number;
  avg_people_in_territory: number;
  avg_gt_in_territory?: number;
  events: { enter: number; exit: number };
  events_dataset_labels?: { enter: number; exit: number };
  events_match?: { matched: number; precision: number; recall: number };
  vs_dataset_labels?: { territory: { precision: number; recall: number; f1: number; count_mae: number; pos_err_cm: number } };
}

export interface DrawOptions {
  boxes: boolean;
  ids: boolean;
  territory: boolean;
}

export const COLOR_IN = "#4ade80";
export const COLOR_OUT = "#fb923c";
const COLOR_WEAK = "rgba(210,210,210,0.55)";
const COLOR_TERR = "#38bdf8";

/** Рамки в момент t: между кадрами детекции рамки одного трека плавно интерполируются. */
export function boxesAt(data: LabData, cam: number, t: number): Box[] {
  const frames = data.boxes[cam];
  const kf = t * data.fps;
  const k0 = Math.max(0, Math.min(frames.length - 1, Math.floor(kf)));
  const a = kf - k0;
  const cur = frames[k0] ?? [];
  const next = frames[k0 + 1];
  if (!next || a <= 0) return cur;
  const byTrack = new Map<number, Box>();
  for (const b of next) if (b[4] >= 0) byTrack.set(b[4], b);
  return cur.map((b) => {
    const n = b[4] >= 0 ? byTrack.get(b[4]) : undefined;
    if (!n) return b;
    return [b[0] + (n[0] - b[0]) * a, b[1] + (n[1] - b[1]) * a, b[2] + (n[2] - b[2]) * a, b[3] + (n[3] - b[3]) * a, b[4], b[5]];
  });
}

export function fitCanvas(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(canvas.clientWidth * dpr);
  const h = Math.round(canvas.clientHeight * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
  }
  const ctx = canvas.getContext("2d")!;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return ctx;
}

/** Кадр камеры (плитка из общего видео-мозаики) и наложения поверх него. */
export function drawCameraView(
  canvas: HTMLCanvasElement,
  data: LabData,
  cam: number,
  t: number,
  opt: DrawOptions,
  video: HTMLVideoElement | null,
) {
  const ctx = fitCanvas(canvas);
  const W = canvas.width;
  const H = canvas.height;
  const dpr = window.devicePixelRatio || 1;
  if (video && video.readyState >= 2) {
    const [tx, ty] = data.mosaic.tiles[cam];
    ctx.drawImage(video, tx, ty, data.mosaic.tile_w, data.mosaic.tile_h, 0, 0, W, H);
  }

  if (opt.territory) {
    ctx.strokeStyle = COLOR_TERR;
    ctx.lineWidth = 2 * dpr;
    for (const run of data.cameras[cam].territory) {
      ctx.beginPath();
      run.forEach(([u, v], i) => (i ? ctx.lineTo(u * W, v * H) : ctx.moveTo(u * W, v * H)));
      ctx.stroke();
    }
  }
  if (!opt.boxes) return;
  const sx = W / data.source.width;
  const sy = H / data.source.height;
  ctx.font = `${Math.max(10, Math.round(11 * dpr))}px Inter, system-ui, sans-serif`;
  ctx.textBaseline = "bottom";
  for (const [x1, y1, x2, y2, track, state] of boxesAt(data, cam, t)) {
    const color = state === 1 ? COLOR_IN : state === 0 ? COLOR_OUT : COLOR_WEAK;
    ctx.strokeStyle = color;
    ctx.lineWidth = (state === -1 ? 1 : 2) * dpr;
    ctx.strokeRect(x1 * sx, y1 * sy, (x2 - x1) * sx, (y2 - y1) * sy);
    if (opt.ids && track >= 0 && state === 1) {
      const label = String(track);
      const tw = ctx.measureText(label).width + 6 * dpr;
      ctx.fillStyle = color;
      ctx.fillRect(x1 * sx, y1 * sy - 14 * dpr, tw, 14 * dpr);
      ctx.fillStyle = "#0b1220";
      ctx.fillText(label, x1 * sx + 3 * dpr, y1 * sy - 1 * dpr);
    }
  }
}

// ---- вид сверху ------------------------------------------------------------------------
// Площадка вытянута (12 × 36 м), поэтому кладём её горизонтально: ось Y земли идёт вправо, X — вниз.

export interface GroundView {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export function groundView(data: LabData): GroundView {
  const xs = [data.ground.x_min, data.ground.x_max, ...data.cameras.map((c) => c.position[0])];
  const ys = [data.ground.y_min, data.ground.y_max, ...data.cameras.map((c) => c.position[1])];
  return { x0: Math.min(...xs) - 1, x1: Math.max(...xs) + 1, y0: Math.min(...ys) - 1, y1: Math.max(...ys) + 1 };
}

export const groundAspect = (v: GroundView) => (v.y1 - v.y0) / (v.x1 - v.x0);

function toPx(v: GroundView, W: number, H: number, x: number, y: number): [number, number] {
  return [((y - v.y0) / (v.y1 - v.y0)) * W, ((x - v.x0) / (v.x1 - v.x0)) * H];
}

const RAMP: [number, [number, number, number]][] = [
  [0, [30, 64, 255]],
  [0.3, [0, 220, 255]],
  [0.55, [60, 220, 80]],
  [0.78, [255, 225, 0]],
  [1, [255, 40, 30]],
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

/** Тепловой слой: пятна в канал прозрачности, затем раскраска. points: [x м, y м, вес 0..1]. */
export function renderHeat(W: number, H: number, v: GroundView, points: [number, number, number][], radiusM: number): HTMLCanvasElement {
  const off = document.createElement("canvas");
  off.width = W;
  off.height = H;
  const o = off.getContext("2d")!;
  const r = (radiusM / (v.y1 - v.y0)) * W;
  for (const [x, y, w] of points) {
    const [px, py] = toPx(v, W, H, x, y);
    const g = o.createRadialGradient(px, py, 0, px, py, r);
    g.addColorStop(0, `rgba(0,0,0,${Math.min(1, w)})`);
    g.addColorStop(1, "rgba(0,0,0,0)");
    o.fillStyle = g;
    o.fillRect(px - r, py - r, 2 * r, 2 * r);
  }
  const img = o.getImageData(0, 0, W, H);
  const d = img.data;
  let max = 1;
  for (let i = 3; i < d.length; i += 4) max = Math.max(max, d[i]);
  for (let i = 0; i < d.length; i += 4) {
    const a = d[i + 3];
    if (a < 3) {
      d[i + 3] = 0;
      continue;
    }
    const [cr, cg, cb] = ramp(a / max);
    d[i] = cr;
    d[i + 1] = cg;
    d[i + 2] = cb;
    d[i + 3] = Math.min(210, 60 + (a / max) * 190);
  }
  o.putImageData(img, 0, 0);
  return off;
}

export function heatPointsAllTime(data: LabData): [number, number, number][] {
  const { rows, cols, values } = data.heat;
  const pts: [number, number, number][] = [];
  const cell = (data.ground.x_max - data.ground.x_min) / cols;
  for (let iy = 0; iy < rows; iy++) {
    for (let ix = 0; ix < cols; ix++) {
      const val = values[iy * cols + ix];
      if (val > 4) pts.push([data.ground.x_min + (ix + 0.5) * cell, data.ground.y_min + (iy + 0.5) * cell, (val / 255) * 0.35]);
    }
  }
  return pts;
}

export function heatPointsWindow(data: LabData, t: number, windowS: number): [number, number, number][] {
  const k1 = Math.min(data.frames.length - 1, Math.floor(t * data.fps));
  const k0 = Math.max(0, k1 - Math.round(windowS * data.fps));
  const pts: [number, number, number][] = [];
  for (let k = k0; k <= k1; k++) for (const [, x, y] of data.frames[k].p) pts.push([x, y, 0.06]);
  return pts;
}

export function drawGround(
  canvas: HTMLCanvasElement,
  data: LabData,
  v: GroundView,
  t: number,
  heat: HTMLCanvasElement | null,
  showIds: boolean,
) {
  const ctx = fitCanvas(canvas);
  const W = canvas.width;
  const H = canvas.height;
  const dpr = window.devicePixelRatio || 1;
  const P = (x: number, y: number) => toPx(v, W, H, x, y);

  ctx.fillStyle = "#0f172a";
  ctx.fillRect(0, 0, W, H);
  // размеченная площадка
  const [ax, ay] = P(data.ground.x_min, data.ground.y_min);
  const [bx, by] = P(data.ground.x_max, data.ground.y_max);
  ctx.fillStyle = "#1e293b";
  ctx.fillRect(ax, ay, bx - ax, by - ay);
  // сетка 5 м
  ctx.strokeStyle = "rgba(148,163,184,0.12)";
  ctx.lineWidth = 1;
  for (let y = Math.ceil(v.y0 / 5) * 5; y <= v.y1; y += 5) {
    const [px] = P(0, y);
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke();
  }
  for (let x = Math.ceil(v.x0 / 5) * 5; x <= v.x1; x += 5) {
    const [, py] = P(x, 0);
    ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(W, py); ctx.stroke();
  }
  // территория
  ctx.fillStyle = "rgba(56,189,248,0.10)";
  ctx.strokeStyle = COLOR_TERR;
  ctx.lineWidth = 2 * dpr;
  for (const poly of data.ground.territory) {
    ctx.beginPath();
    poly.forEach(([x, y], i) => { const [px, py] = P(x, y); if (i) ctx.lineTo(px, py); else ctx.moveTo(px, py); });
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
  }
  if (heat) ctx.drawImage(heat, 0, 0, W, H);

  // камеры
  ctx.font = `${Math.round(11 * dpr)}px Inter, system-ui, sans-serif`;
  for (const cam of data.cameras) {
    const [px, py] = P(cam.position[0], cam.position[1]);
    ctx.fillStyle = "#e2e8f0";
    ctx.beginPath();
    ctx.moveTo(px, py - 7 * dpr); ctx.lineTo(px - 6 * dpr, py + 5 * dpr); ctx.lineTo(px + 6 * dpr, py + 5 * dpr);
    ctx.closePath();
    ctx.fill();
    ctx.fillText(cam.name, px + 8 * dpr, py + 4 * dpr);
  }

  const k = Math.max(0, Math.min(data.frames.length - 1, Math.floor(t * data.fps)));
  // следы за 3 секунды
  const trail = new Map<number, [number, number][]>();
  for (let j = Math.max(0, k - 3 * data.fps); j <= k; j++) {
    for (const [track, x, y] of data.frames[j].p) {
      if (track < 0) continue;
      const arr = trail.get(track) ?? [];
      arr.push(P(x, y));
      trail.set(track, arr);
    }
  }
  ctx.strokeStyle = "rgba(226,232,240,0.35)";
  ctx.lineWidth = 1.5 * dpr;
  for (const pts of trail.values()) {
    if (pts.length < 2) continue;
    ctx.beginPath();
    pts.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
    ctx.stroke();
  }
  // люди
  for (const [track, x, y, inside] of data.frames[k].p) {
    const [px, py] = P(x, y);
    ctx.fillStyle = inside ? COLOR_IN : COLOR_OUT;
    ctx.beginPath();
    ctx.arc(px, py, 4.5 * dpr, 0, Math.PI * 2);
    ctx.fill();
    if (showIds && track >= 0 && inside) {
      ctx.fillStyle = "#cbd5e1";
      ctx.fillText(String(track), px + 6 * dpr, py - 4 * dpr);
    }
  }
  // вспышки заходов/выходов за последние 1.5 с
  for (const e of data.events) {
    const age = t - e.t;
    if (age < 0 || age > 1.5) continue;
    const [px, py] = P(e.x, e.y);
    ctx.strokeStyle = e.kind === "enter" ? COLOR_IN : COLOR_OUT;
    ctx.globalAlpha = 1 - age / 1.5;
    ctx.lineWidth = 2.5 * dpr;
    ctx.beginPath();
    ctx.arc(px, py, (6 + age * 14) * dpr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
}
