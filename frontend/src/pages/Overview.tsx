import { useMemo } from "react";
import { type TrafficPoint, qs } from "../api";
import { useLive } from "../App";
import Chart, { COLORS } from "../components/Chart";
import { Kpi, PageHead } from "../components/ui";
import { useApi } from "../hooks";
import { fmtDelta, fmtDuration, fmtNum, fmtTime, loadLevel, startOfDay } from "../lib/format";

function LoadBar({ value, capacity }: { value: number; capacity: number | null }) {
  const ratio = capacity ? value / capacity : 0;
  return (
    <div className={`bar lvl-${loadLevel(ratio)}`}>
      <i style={{ width: `${Math.min(100, ratio * 100)}%` }} />
    </div>
  );
}

export default function OverviewPage() {
  const live = useLive();
  const range = useMemo(() => {
    const from = startOfDay(new Date());
    return qs({ from: from.toISOString(), to: new Date(from.getTime() + 86_400_000).toISOString(), bucket: "hour" });
  }, []);
  const { data: traffic } = useApi<TrafficPoint[]>(`/api/traffic?${range}`, 60_000);

  if (!live) return <div className="empty">Загрузка…</div>;

  const { occupancy: occ } = live;
  const ratio = occ.mall_capacity ? occ.mall / occ.mall_capacity : 0;
  const delta = fmtDelta(live.visitors_today, live.visitors_yesterday_same_time);
  const worstQueue = live.queues.filter((q) => !q.stale).sort((a, b) => b.max_wait_sec - a.max_wait_sec)[0];

  const hourLabels = (traffic ?? []).map((p) => fmtTime(p.ts));
  const nowIdx = (traffic ?? []).findIndex((p) => new Date(p.ts).getTime() > Date.now()) - 1;

  return (
    <>
      <PageHead title="Обзор" />

      {live.alerts.map((a) => (
        <div className="alert-banner" key={a.id}>
          <b>⚠</b>
          <div>
            {a.message} <span className="muted">· с {fmtTime(a.started_at)}</span>
          </div>
        </div>
      ))}

      <div className="grid hero">
        <div className="card">
          <h2>Сейчас в ТЦ</h2>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14 }}>
            <span className="big-number">{fmtNum(occ.mall)}</span>
            <span className="muted">
              {occ.mall_capacity ? `из ${fmtNum(occ.mall_capacity)} · ${Math.round(ratio * 100)}%` : "вместимость не задана"}
            </span>
          </div>
          <div style={{ marginTop: 14 }}>
            <LoadBar value={occ.mall} capacity={occ.mall_capacity} />
          </div>
          {occ.floors.map((f) => (
            <div className="floor-row" key={f.id}>
              <div className="head">
                <span>{f.name}</span>
                <span className="muted">
                  {fmtNum(f.occupancy)}
                  {f.capacity ? ` / ${fmtNum(f.capacity)}` : ""}
                </span>
              </div>
              <LoadBar value={f.occupancy} capacity={f.capacity} />
            </div>
          ))}
        </div>

        <div className="grid" style={{ alignContent: "start" }}>
          <Kpi
            label="Посетителей сегодня"
            value={fmtNum(live.visitors_today)}
            sub={delta.text}
            tone={delta.up === null ? null : delta.up ? "up" : "down"}
          />
          <Kpi
            label="Самая долгая очередь"
            value={worstQueue ? fmtDuration(worstQueue.max_wait_sec) : "—"}
            sub={worstQueue ? `${worstQueue.name}: ${worstQueue.people} чел.` : "нет данных"}
          />
          <Kpi label="Активные оповещения" value={live.alerts.length} sub={live.alerts.length ? "требуют внимания" : "всё в норме"} tone={live.alerts.length ? "down" : "up"} />
        </div>
      </div>

      <div className="card mt">
        <h2>Сегодня по часам</h2>
        <Chart
          height={300}
          option={{
            xAxis: { type: "category", data: hourLabels, axisLabel: { color: "#6b7686" } },
            yAxis: [
              { type: "value", name: "вход / выход", nameTextStyle: { color: "#6b7686" } },
              { type: "value", name: "в ТЦ", nameTextStyle: { color: "#6b7686" }, splitLine: { show: false } },
            ],
            series: [
              { name: "Вход", type: "bar", data: (traffic ?? []).map((p) => p.in), color: COLORS.in, barMaxWidth: 18 },
              { name: "Выход", type: "bar", data: (traffic ?? []).map((p) => p.out), color: COLORS.out, barMaxWidth: 18 },
              {
                name: "Заполняемость",
                type: "line",
                yAxisIndex: 1,
                smooth: true,
                symbol: "none",
                color: COLORS.occupancy,
                lineStyle: { width: 3 },
                data: (traffic ?? []).map((p, i) => (nowIdx >= 0 && i > nowIdx ? null : p.occupancy)),
              },
            ],
          }}
        />
      </div>

      <div className="grid cols-2 mt">
        {live.queues.map((q) => {
          const level = q.stale ? "off" : q.people >= 9 || q.max_wait_sec >= 300 ? "bad" : q.people >= 5 ? "warn" : "ok";
          return (
            <div className="card" key={q.zone_id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div className="muted">{q.name}</div>
                <div style={{ fontSize: 26, fontWeight: 700 }}>{q.stale ? "—" : `${q.people} чел.`}</div>
              </div>
              <span className={`pill ${level}`}>{q.stale ? "нет данных" : `ожидание ${fmtDuration(q.max_wait_sec)}`}</span>
            </div>
          );
        })}
      </div>
    </>
  );
}
