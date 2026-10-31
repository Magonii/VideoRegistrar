import { useState } from "react";
import { type Camera, type Floor, api } from "../api";
import CameraEditor from "../components/CameraEditor";
import { ErrorBox, Modal, PageHead } from "../components/ui";
import { useApi } from "../hooks";
import { fmtDateTime } from "../lib/format";

type Draft = { id?: number; name: string; rtsp_url: string; floor_id: number | null; enabled: boolean; homography: number[][] | null };

export default function Cameras() {
  const { data: cameras, reload } = useApi<Camera[]>("/api/cameras", 10_000);
  const { data: floors } = useApi<Floor[]>("/api/floors");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const editing = cameras?.find((c) => c.id === editingId) ?? null;
  const floorName = (id: number | null) => floors?.find((f) => f.id === id)?.name ?? "—";

  async function save() {
    if (!draft) return;
    setError(null);
    try {
      const { id, ...body } = draft;
      await api(id ? `/api/cameras/${id}` : "/api/cameras", { method: id ? "PUT" : "POST", json: body });
      setDraft(null);
      reload();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function remove(c: Camera) {
    if (!confirm(`Удалить камеру «${c.name}» вместе с её линиями и зонами? История событий сохранится.`)) return;
    await api(`/api/cameras/${c.id}`, { method: "DELETE" });
    reload();
  }

  return (
    <>
      <PageHead title="Камеры">
        <button className="btn primary" onClick={() => setDraft({ name: "", rtsp_url: "", floor_id: floors?.[0]?.id ?? null, enabled: true, homography: null })}>
          + Добавить камеру
        </button>
      </PageHead>

      <div className="card">
        {cameras && cameras.length === 0 && <div className="empty">Камер нет. Добавьте камеру и нарисуйте линии подсчёта.</div>}
        <table>
          <thead>
            <tr><th>Камера</th><th>Этаж</th><th>Разметка</th><th>Привязка к плану</th><th>Статус</th><th /></tr>
          </thead>
          <tbody>
            {(cameras ?? []).map((c) => (
              <tr key={c.id}>
                <td>
                  <b>{c.name}</b>
                  <div className="muted" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.rtsp_url || "адрес потока не задан"}</div>
                </td>
                <td>{floorName(c.floor_id)}</td>
                <td>{c.lines.length} лин. · {c.zones.length} зон</td>
                <td>{c.homography ? <span className="pill ok">есть</span> : <span className="pill off">нет</span>}</td>
                <td>
                  <span className={`dot ${c.online ? "on" : ""}`} />{" "}
                  {c.online ? "в сети" : c.last_seen ? `был ${fmtDateTime(c.last_seen)}` : "не подключалась"}
                </td>
                <td className="actions">
                  <button className="btn sm primary" onClick={() => setEditingId(c.id)}>Разметка</button>{" "}
                  <button className="btn sm" onClick={() => setDraft({ id: c.id, name: c.name, rtsp_url: c.rtsp_url, floor_id: c.floor_id, enabled: c.enabled, homography: c.homography })}>Свойства</button>{" "}
                  <button className="btn sm danger" onClick={() => remove(c)}>Удалить</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted" style={{ marginBottom: 0 }}>
          Запуск обработки камеры: <code>python -m worker --camera-id &lt;номер&gt; --backend http://сервер:8000</code>
        </p>
      </div>

      {draft && (
        <Modal narrow title={draft.id ? "Свойства камеры" : "Новая камера"} onClose={() => setDraft(null)}>
          <div className="form-grid">
            <ErrorBox message={error} />
            <label className="field">Название
              <input type="text" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="Главный вход" />
            </label>
            <label className="field">Адрес потока (RTSP)
              <input type="text" value={draft.rtsp_url} onChange={(e) => setDraft({ ...draft, rtsp_url: e.target.value })} placeholder="rtsp://user:pass@192.168.1.10:554/stream1" />
            </label>
            <label className="field">Этаж
              <select value={draft.floor_id ?? ""} onChange={(e) => setDraft({ ...draft, floor_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">—</option>
                {floors?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </label>
            <label className="check"><input type="checkbox" checked={draft.enabled} onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })} /> Камера включена</label>
            <button className="btn primary" disabled={!draft.name.trim()} onClick={save}>Сохранить</button>
          </div>
        </Modal>
      )}

      {editing && floors && (
        <Modal title={`Разметка: ${editing.name}`} onClose={() => setEditingId(null)}>
          <CameraEditor key={editing.id} camera={editing} floors={floors} onSaved={reload} />
        </Modal>
      )}
    </>
  );
}
