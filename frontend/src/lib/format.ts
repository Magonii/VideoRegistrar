const nf = new Intl.NumberFormat("ru-RU");

export const fmtNum = (n: number | null | undefined) => (n == null ? "—" : nf.format(Math.round(n)));

export function fmtDuration(sec: number): string {
  if (sec < 60) return `${Math.round(sec)} с`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return s ? `${m} мин ${s} с` : `${m} мин`;
}

export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });

export const fmtDateTime = (iso: string) =>
  new Date(iso).toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export function fmtDelta(now: number, before: number): { text: string; up: boolean | null } {
  if (before <= 0) return { text: "нет данных за вчера", up: null };
  const pct = ((now - before) / before) * 100;
  return { text: `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% к вчера`, up: pct >= 0 };
}

export function startOfDay(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}

export const addDays = (d: Date, n: number) => new Date(d.getTime() + n * 86_400_000);

export function dateInputValue(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/** Цвет статуса по доле заполнения: зелёный → жёлтый → красный. */
export function loadLevel(ratio: number): "ok" | "warn" | "bad" {
  return ratio >= 0.85 ? "bad" : ratio >= 0.7 ? "warn" : "ok";
}

export const METRIC_LABELS: Record<string, string> = {
  occupancy_mall: "Заполняемость ТЦ (человек)",
  occupancy_floor: "Заполняемость этажа (человек)",
  queue_people: "Длина очереди (человек)",
  queue_wait: "Ожидание в очереди (секунд)",
};
