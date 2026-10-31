export type Pt = [number, number];

export interface Floor {
  id: number;
  name: string;
  sort: number;
  capacity: number | null;
  has_plan: boolean;
}

export interface Line {
  id?: number;
  camera_id?: number;
  name: string;
  p1: Pt;
  p2: Pt;
  in_side: 1 | -1;
  floor_in_id: number | null;
  floor_out_id: number | null;
}

export interface Zone {
  id?: number;
  camera_id?: number;
  name: string;
  kind: "queue" | "area";
  polygon: Pt[];
  floor_id: number | null;
  min_dwell_sec: number;
}

export interface Camera {
  id: number;
  name: string;
  rtsp_url: string;
  floor_id: number | null;
  enabled: boolean;
  homography: number[][] | null;
  online: boolean;
  has_snapshot: boolean;
  last_seen: string | null;
  lines: Line[];
  zones: Zone[];
}

export interface QueueState {
  zone_id: number;
  name: string;
  floor_id: number | null;
  camera_id: number;
  people: number;
  max_wait_sec: number;
  stale: boolean;
  ts: string | null;
}

export interface ActiveAlert {
  id: number;
  rule_id: number;
  rule_name: string;
  started_at: string;
  peak_value: number;
  message: string;
}

export interface Overview {
  ts: string;
  occupancy: {
    mall: number;
    mall_capacity: number | null;
    floors: { id: number; name: string; occupancy: number; capacity: number | null }[];
  };
  visitors_today: number;
  visitors_yesterday_same_time: number;
  queues: QueueState[];
  alerts: ActiveAlert[];
}

export interface TrafficPoint {
  ts: string;
  in: number;
  out: number;
  occupancy: number | null;
}

export interface Heatmap {
  cols: number;
  rows: number;
  cells: number[];
  max: number;
  total: number;
}

export interface QueueHistoryPoint {
  ts: string;
  people_max: number;
  people_avg: number;
  wait_max_sec: number;
}

export type Metric = "occupancy_mall" | "occupancy_floor" | "queue_people" | "queue_wait";

export interface AlertRule {
  id: number;
  name: string;
  metric: Metric;
  target_id: number | null;
  threshold: number;
  min_duration_sec: number;
  enabled: boolean;
  notify: boolean;
}

export interface AlertEventRow {
  id: number;
  rule_id: number;
  rule_name: string;
  started_at: string;
  resolved_at: string | null;
  peak_value: number;
  message: string;
}

export async function api<T = unknown>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const res = await fetch(path, {
    ...rest,
    headers: json !== undefined ? { "Content-Type": "application/json", ...rest.headers } : rest.headers,
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* тело не JSON */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export function qs(params: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined) p.set(k, String(v));
  return p.toString();
}
