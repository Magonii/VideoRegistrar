import { useState } from "react";
import { type AlertEventRow, type AlertRule, type Camera, type Floor, type Metric, api } from "../api";
import { useLive } from "../App";
import { ErrorBox, Modal, PageHead } from "../components/ui";
import { useApi } from "../hooks";
import { METRIC_LABELS, fmtDateTime, fmtDuration } from "../lib/format";

type Draft = Omit<AlertRule, "id"> & { id?: number };

const EMPTY: Draft = { name: "", metric: "occupancy_mall", target_id: null, threshold: 100, min_duration_sec: 60, enabled: true, notify: true };

export default function Alerts() {
  const live = useLive();
  const { data: rules, reload: reloadRules } = useApi<AlertRule[]>("/api/alert-rules");
  const { data: events } = useApi<AlertEventRow[]>("/api/alerts?limit=50", 10_000);
  const { data: floors } = useApi<Floor[]>("/api/floors");
  const { data: cameras } = useApi<Camera[]>("/api/cameras");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  const zones = (cameras ?? []).flatMap((c) => c.zones.filter((z) => z.kind === "queue"));

  async function save() {
    if (!draft) return;
    setError(null);
    try {
      const { id, ...body } = draft;
      await api(id ? `/api/alert-rules/${id}` : "/api/alert-rules", { method: id ? "PUT" : "POST", json: body });
      setDraft(null);
      void reloadRules();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(rule: AlertRule) {
    if (!confirm(`Удалить правило «${rule.name}»?`)) return;
    await api(`/api/alert-rules/${rule.id}`, { method: "DELETE" });
    void reloadRules();
  }

  async function toggle(rule: AlertRule) {
    const { id, ...body } = rule;
    await api(`/api/alert-rules/${id}`, { method: "PUT", json: { ...body, enabled: !rule.enabled } });
    void reloadRules();
  }

  const targetName = (r: AlertRule) => {
    if (!r.target_id) return r.metric === "occupancy_mall" ? "весь ТЦ" : "любая зона / этаж";
    if (r.metric === "occupancy_floor") return floors?.find((f) => f.id === r.target_id)?.name ?? `#${r.target_id}`;
    return zones.find((z) => z.id === r.target_id)?.name ?? `#${r.target_id}`;
  };

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => (d ? { ...d, [k]: v } : d));

  return (
    <>
      <PageHead title="Оповещения">
        <button className="btn primary" onClick={() => setDraft({ ...EMPTY })}>
          + Новое правило
        </button>
      </PageHead>

      {live?.alerts.map((a) => (
        <div className="alert-banner" key={a.id}>
          <b>⚠</b>
          <div>
            {a.message} <span className="muted">· с {fmtDateTime(a.started_at)}</span>
          </div>
        </div>
      ))}

      <div className="card">
        <h2>Правила</h2>
        {rules && rules.length === 0 && <div className="empty">Правил пока нет</div>}
        <table>
          <tbody>
            {(rules ?? []).map((r) => (
              <tr key={r.id} style={{ opacity: r.enabled ? 1 : 0.5 }}>
                <td>
                  <b>{r.name}</b>
                  <div className="muted">
                    {METRIC_LABELS[r.metric]} · {targetName(r)}
                  </div>
                </td>
                <td>
                  выше <b>{r.threshold}</b>
                  <div className="muted">дольше {fmtDuration(r.min_duration_sec)}</div>
                </td>
                <td>{r.notify ? "Telegram" : "только в системе"}</td>
                <td className="actions">
                  <button className="btn sm" onClick={() => toggle(r)}>{r.enabled ? "Выключить" : "Включить"}</button>{" "}
                  <button className="btn sm" onClick={() => setDraft({ ...r })}>Изменить</button>{" "}
                  <button className="btn sm danger" onClick={() => remove(r)}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card mt">
        <h2>Журнал</h2>
        {events && events.length === 0 && <div className="empty">Срабатываний не было</div>}
        <table>
          <thead>
            <tr><th>Начало</th><th>Правило</th><th>Пик</th><th>Статус</th></tr>
          </thead>
          <tbody>
            {(events ?? []).map((e) => (
              <tr key={e.id}>
                <td>{fmtDateTime(e.started_at)}</td>
                <td>{e.message || e.rule_name}</td>
                <td>{e.peak_value}</td>
                <td>
                  {e.resolved_at ? <span className="pill ok">закрыто {fmtDateTime(e.resolved_at)}</span> : <span className="pill bad">активно</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {draft && (
        <Modal narrow title={draft.id ? "Правило оповещения" : "Новое правило"} onClose={() => setDraft(null)}>
          <div className="form-grid">
            <ErrorBox message={error} />
            <label className="field">Название
              <input type="text" value={draft.name} onChange={(e) => set("name", e.target.value)} placeholder="Например: очередь на фудкорте" />
            </label>
            <label className="field">Что отслеживаем
              <select value={draft.metric} onChange={(e) => { set("metric", e.target.value as Metric); set("target_id", null); }}>
                {Object.entries(METRIC_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </label>
            {draft.metric === "occupancy_floor" && (
              <label className="field">Этаж
                <select value={draft.target_id ?? ""} onChange={(e) => set("target_id", e.target.value ? Number(e.target.value) : null)}>
                  <option value="">Любой</option>
                  {floors?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                </select>
              </label>
            )}
            {draft.metric.startsWith("queue") && (
              <label className="field">Зона очереди
                <select value={draft.target_id ?? ""} onChange={(e) => set("target_id", e.target.value ? Number(e.target.value) : null)}>
                  <option value="">Любая</option>
                  {zones.map((z) => <option key={z.id} value={z.id}>{z.name}</option>)}
                </select>
              </label>
            )}
            <div className="grid cols-2">
              <label className="field">Порог (выше)
                <input type="number" value={draft.threshold} onChange={(e) => set("threshold", Number(e.target.value))} />
              </label>
              <label className="field">Дольше, секунд
                <input type="number" min={0} value={draft.min_duration_sec} onChange={(e) => set("min_duration_sec", Number(e.target.value))} />
              </label>
            </div>
            <label className="check"><input type="checkbox" checked={draft.notify} onChange={(e) => set("notify", e.target.checked)} /> Отправлять уведомление в Telegram</label>
            <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Правило включено</label>
            <button className="btn primary" disabled={!draft.name.trim()} onClick={save}>Сохранить</button>
          </div>
        </Modal>
      )}
    </>
  );
}
