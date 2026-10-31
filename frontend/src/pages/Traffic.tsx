import { useMemo, useState } from "react";
import { type Floor, type TrafficPoint, qs } from "../api";
import Chart, { COLORS } from "../components/Chart";
import { ErrorBox, Kpi, PageHead, Segmented } from "../components/ui";
import { useApi } from "../hooks";
import { addDays, fmtNum, startOfDay } from "../lib/format";

type Period = "today" | "yesterday" | "7d" | "30d";
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const weekday = (d: Date) => (d.getDay() + 6) % 7;

function rangeFor(period: Period): { from: Date; to: Date } {
  const today = startOfDay(new Date());
  switch (period) {
    case "today":
      return { from: today, to: addDays(today, 1) };
    case "yesterday":
      return { from: addDays(today, -1), to: today };
    case "7d":
      return { from: addDays(today, -6), to: addDays(today, 1) };
    case "30d":
      return { from: addDays(today, -29), to: addDays(today, 1) };
  }
}

export default function Traffic() {
  const [period, setPeriod] = useState<Period>("7d");
  const [floorId, setFloorId] = useState<number | "">("");
  const { data: floors } = useApi<Floor[]>("/api/floors");

  const query = useMemo(() => {
    const { from, to } = rangeFor(period);
    return qs({ from: from.toISOString(), to: to.toISOString(), bucket: "hour", floor_id: floorId === "" ? null : floorId });
  }, [period, floorId]);
  const { data, error } = useApi<TrafficPoint[]>(`/api/traffic?${query}`, 60_000);

  const stats = useMemo(() => {
    const rows = (data ?? []).map((p) => ({ ...p, date: new Date(p.ts) }));
    const totalIn = rows.reduce((s, r) => s + r.in, 0);
    const totalOut = rows.reduce((s, r) => s + r.out, 0);
    const peakHour = rows.reduce((best, r) => (r.in > best.in ? r : best), rows[0] ?? { in: 0, date: new Date(), occupancy: 0 });
    const peakOcc = rows.reduce((m, r) => Math.max(m, r.occupancy ?? 0), 0);

    const daily = period === "7d" || period === "30d";
    const chartRows = daily ? aggregateDays(rows) : rows.map((r) => ({ label: r.date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }), in: r.in, out: r.out, occupancy: r.occupancy }));

    // средний вход по дню недели и часу — «когда у нас пик»
    const sum = Array.from({ length: 7 }, () => new Array<number>(24).fill(0));
    const days = Array.from({ length: 7 }, () => new Set<string>());
    for (const r of rows) {
      sum[weekday(r.date)][r.date.getHours()] += r.in;
      days[weekday(r.date)].add(r.date.toDateString());
    }
    const heat: [number, number, number][] = [];
    let heatMax = 0;
    sum.forEach((hours, d) =>
      hours.forEach((v, h) => {
        const avg = days[d].size ? Math.round(v / days[d].size) : 0;
        heatMax = Math.max(heatMax, avg);
        heat.push([h, d, avg]);
      }),
    );
    return { totalIn, totalOut, peakHour, peakOcc, chartRows, heat, heatMax, daily };
  }, [data, period]);

  return (
    <>
      <PageHead title="Трафик">
        <select value={floorId} onChange={(e) => setFloorId(e.target.value === "" ? "" : Number(e.target.value))}>
          <option value="">Весь ТЦ (входы с улицы)</option>
          {floors?.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
        <Segmented
          value={period}
          onChange={setPeriod}
          options={[
            { value: "today", label: "Сегодня" },
            { value: "yesterday", label: "Вчера" },
            { value: "7d", label: "7 дней" },
            { value: "30d", label: "30 дней" },
          ]}
        />
      </PageHead>
      <ErrorBox message={error} />

      <div className="grid cols-4">
        <Kpi label="Вошли" value={fmtNum(stats.totalIn)} />
        <Kpi label="Вышли" value={fmtNum(stats.totalOut)} />
        <Kpi
          label="Час пик"
          value={stats.peakHour.in ? `${String(stats.peakHour.date.getHours()).padStart(2, "0")}:00` : "—"}
          sub={stats.peakHour.in ? `${fmtNum(stats.peakHour.in)} входов · ${stats.peakHour.date.toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}` : undefined}
        />
        <Kpi label="Максимум в ТЦ одновременно" value={fmtNum(stats.peakOcc)} />
      </div>

      <div className="card mt">
        <h2>{stats.daily ? "Входы и выходы по дням" : "Входы и выходы по часам"}</h2>
        <Chart
          option={{
            xAxis: { type: "category", data: stats.chartRows.map((r) => r.label), axisLabel: { color: "#6b7686" } },
            yAxis: { type: "value" },
            series: [
              { name: "Вход", type: "bar", color: COLORS.in, barMaxWidth: 26, data: stats.chartRows.map((r) => r.in) },
              { name: "Выход", type: "bar", color: COLORS.out, barMaxWidth: 26, data: stats.chartRows.map((r) => r.out) },
            ],
          }}
        />
      </div>

      {!stats.daily && (
        <div className="card mt">
          <h2>Заполняемость на конец каждого часа</h2>
          <Chart
            height={240}
            option={{
              xAxis: { type: "category", data: stats.chartRows.map((r) => r.label), axisLabel: { color: "#6b7686" } },
              yAxis: { type: "value" },
              series: [{ name: "Людей внутри", type: "line", smooth: true, symbol: "none", areaStyle: { opacity: 0.15 }, color: COLORS.occupancy, lineStyle: { width: 3 }, data: stats.chartRows.map((r) => r.occupancy) }],
            }}
          />
        </div>
      )}

      <div className="card mt">
        <h2>Когда у нас пик: средние входы по дню недели и часу</h2>
        <Chart
          height={300}
          option={{
            tooltip: { formatter: (p: unknown) => { const v = (p as { value: [number, number, number] }).value; return `${WEEKDAYS[v[1]]}, ${v[0]}:00 — в среднем ${v[2]} входов`; } },
            grid: { left: 40, right: 24, top: 10, bottom: 56 },
            xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => String(h)), splitArea: { show: true } },
            yAxis: { type: "category", data: WEEKDAYS, inverse: true },
            visualMap: { min: 0, max: Math.max(stats.heatMax, 1), calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#f0f5ff", "#7fa8ff", "#2f6df6", "#10256e"] } },
            series: [{ type: "heatmap", data: stats.heat }],
          }}
        />
      </div>
    </>
  );
}

function aggregateDays(rows: { date: Date; in: number; out: number; occupancy: number | null }[]) {
  const byDay = new Map<string, { label: string; in: number; out: number; occupancy: number | null }>();
  for (const r of rows) {
    const key = r.date.toDateString();
    const item = byDay.get(key) ?? { label: r.date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" }), in: 0, out: 0, occupancy: null };
    item.in += r.in;
    item.out += r.out;
    byDay.set(key, item);
  }
  return [...byDay.values()];
}
