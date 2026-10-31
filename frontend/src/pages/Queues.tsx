import { useEffect, useMemo, useState } from "react";
import { type QueueHistoryPoint, qs } from "../api";
import { useLive } from "../App";
import Chart, { COLORS } from "../components/Chart";
import { PageHead, Segmented } from "../components/ui";
import { useApi } from "../hooks";
import { fmtDuration, fmtTime } from "../lib/format";

type Hours = "2" | "6" | "24";

export function queueLevel(people: number, waitSec: number, stale: boolean): "ok" | "warn" | "bad" | "off" {
  if (stale) return "off";
  if (people >= 9 || waitSec >= 300) return "bad";
  if (people >= 5 || waitSec >= 150) return "warn";
  return "ok";
}

const LEVEL_TEXT = { ok: "свободно", warn: "умеренно", bad: "длинная очередь", off: "нет данных" };

export default function Queues() {
  const live = useLive();
  const [selected, setSelected] = useState<number | null>(null);
  const [hours, setHours] = useState<Hours>("6");

  useEffect(() => {
    if (selected === null && live?.queues.length) setSelected(live.queues[0].zone_id);
  }, [live, selected]);

  const query = useMemo(() => {
    const end = new Date();
    return qs({ from: new Date(end.getTime() - Number(hours) * 3_600_000).toISOString(), to: new Date(end.getTime() + 60_000).toISOString(), step_min: hours === "24" ? 15 : 5 });
  }, [hours, selected]); // eslint-disable-line react-hooks/exhaustive-deps
  const { data: history } = useApi<QueueHistoryPoint[]>(selected ? `/api/queues/${selected}/history?${query}` : null, 30_000);

  if (!live) return <div className="empty">Загрузка…</div>;

  return (
    <>
      <PageHead title="Очереди">
        <Segmented<Hours>
          value={hours}
          onChange={setHours}
          options={[
            { value: "2", label: "2 часа" },
            { value: "6", label: "6 часов" },
            { value: "24", label: "24 часа" },
          ]}
        />
      </PageHead>

      {live.queues.length === 0 && <div className="card empty">Нет зон очередей. Нарисуйте зону типа «очередь» в редакторе камеры.</div>}

      <div className="grid cols-3">
        {live.queues.map((q) => {
          const level = queueLevel(q.people, q.max_wait_sec, q.stale);
          return (
            <div key={q.zone_id} className={`queue-card ${selected === q.zone_id ? "sel" : ""}`} onClick={() => setSelected(q.zone_id)}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                <b>{q.name}</b>
                <span className={`pill ${level}`}>{LEVEL_TEXT[level]}</span>
              </div>
              <div className="n">{q.stale ? "—" : q.people}<span className="muted" style={{ fontSize: 15, fontWeight: 400 }}> чел.</span></div>
              <div className="muted">{q.stale ? "камера не присылает данные" : `ожидание до ${fmtDuration(q.max_wait_sec)}`}</div>
            </div>
          );
        })}
      </div>

      {selected && (
        <div className="card mt">
          <h2>{live.queues.find((q) => q.zone_id === selected)?.name}: динамика</h2>
          {history && history.length === 0 ? (
            <div className="empty">За выбранный период данных нет</div>
          ) : (
            <Chart
              height={320}
              option={{
                xAxis: { type: "category", data: (history ?? []).map((p) => fmtTime(p.ts)), axisLabel: { color: "#6b7686" } },
                yAxis: [
                  { type: "value", name: "человек", minInterval: 1 },
                  { type: "value", name: "минут", splitLine: { show: false } },
                ],
                series: [
                  { name: "В очереди (макс.)", type: "line", step: "middle", symbol: "none", color: COLORS.in, areaStyle: { opacity: 0.12 }, data: (history ?? []).map((p) => p.people_max) },
                  { name: "Ожидание, мин", type: "line", yAxisIndex: 1, smooth: true, symbol: "none", color: COLORS.wait, data: (history ?? []).map((p) => +(p.wait_max_sec / 60).toFixed(1)) },
                ],
              }}
            />
          )}
        </div>
      )}
    </>
  );
}
