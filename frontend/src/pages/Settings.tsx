import { useEffect, useState } from "react";
import { type Floor, api } from "../api";
import { ErrorBox, PageHead } from "../components/ui";
import { useApi } from "../hooks";

function FloorRow({ floor, onChange }: { floor: Floor; onChange: () => void }) {
  const [name, setName] = useState(floor.name);
  const [capacity, setCapacity] = useState(floor.capacity?.toString() ?? "");
  const [error, setError] = useState<string | null>(null);
  const dirty = name !== floor.name || capacity !== (floor.capacity?.toString() ?? "");

  async function run(fn: () => Promise<unknown>) {
    setError(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <tr>
      <td><input type="text" value={name} onChange={(e) => setName(e.target.value)} /></td>
      <td><input type="number" min={0} style={{ width: 110 }} value={capacity} onChange={(e) => setCapacity(e.target.value)} placeholder="не задана" /></td>
      <td>
        {floor.has_plan ? <span className="pill ok">загружен</span> : <span className="pill off">нет</span>}{" "}
        <label className="btn sm" style={{ display: "inline-block" }}>
          Загрузить план
          <input
            type="file"
            accept=".svg,.png,.jpg,.jpeg,.webp"
            hidden
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const body = new FormData();
              body.append("file", file);
              void run(() => api(`/api/floors/${floor.id}/plan`, { method: "POST", body }));
            }}
          />
        </label>
      </td>
      <td className="actions">
        <button className="btn sm primary" disabled={!dirty || !name.trim()} onClick={() => run(() => api(`/api/floors/${floor.id}`, { method: "PUT", json: { name, sort: floor.sort, capacity: capacity ? Number(capacity) : null } }))}>
          Сохранить
        </button>{" "}
        <button className="btn sm danger" onClick={() => confirm(`Удалить «${floor.name}»?`) && run(() => api(`/api/floors/${floor.id}`, { method: "DELETE" }))}>
          Удалить
        </button>
        {error && <div className="muted" style={{ color: "var(--bad)" }}>{error}</div>}
      </td>
    </tr>
  );
}

export default function Settings() {
  const { data: floors, reload } = useApi<Floor[]>("/api/floors");
  const { data: settings, reload: reloadSettings } = useApi<{ mall_capacity: number | null }>("/api/settings");
  const [mallCap, setMallCap] = useState("");
  const [newName, setNewName] = useState("");
  const [corrFloor, setCorrFloor] = useState("");
  const [corrValue, setCorrValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (settings) setMallCap(settings.mall_capacity?.toString() ?? "");
  }, [settings]);

  async function guarded(fn: () => Promise<unknown>, ok?: string) {
    setError(null);
    setNotice(null);
    try {
      await fn();
      if (ok) setNotice(ok);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <PageHead title="Настройки" />
      <ErrorBox message={error} />
      {notice && <div className="card" style={{ marginBottom: 12, background: "var(--ok-soft)" }}>{notice}</div>}

      <div className="card">
        <h2>Вместимость ТЦ</h2>
        <div className="toolbar">
          <input type="number" min={0} value={mallCap} onChange={(e) => setMallCap(e.target.value)} placeholder="человек" />
          <button className="btn primary" onClick={() => guarded(async () => { await api("/api/settings", { method: "PUT", json: { mall_capacity: mallCap ? Number(mallCap) : null } }); reloadSettings(); }, "Сохранено")}>
            Сохранить
          </button>
          <span className="muted">Используется для шкалы заполняемости на странице «Обзор».</span>
        </div>
      </div>

      <div className="card mt">
        <h2>Этажи и планы</h2>
        <table>
          <thead><tr><th>Название</th><th>Вместимость</th><th>План этажа</th><th /></tr></thead>
          <tbody>{(floors ?? []).map((f) => <FloorRow key={`${f.id}-${f.name}-${f.capacity}-${f.has_plan}`} floor={f} onChange={reload} />)}</tbody>
        </table>
        <div className="toolbar mt">
          <input type="text" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="Название нового этажа" />
          <button className="btn" disabled={!newName.trim()} onClick={() => guarded(async () => { await api("/api/floors", { method: "POST", json: { name: newName.trim(), sort: (floors?.length ?? 0) + 1 } }); setNewName(""); reload(); })}>
            + Добавить этаж
          </button>
        </div>
        <p className="muted">План — картинка (SVG, PNG, JPG): по ней строится тепловая карта и привязка камер.</p>
      </div>

      <div className="card mt">
        <h2>Ручная поправка заполняемости</h2>
        <p className="muted" style={{ marginTop: 0 }}>
          Если счётчик накопил ошибку, укажите фактическое число людей на этаже. Дальше подсчёт пойдёт от этого значения.
        </p>
        <div className="toolbar">
          <select value={corrFloor} onChange={(e) => setCorrFloor(e.target.value)}>
            <option value="">Выберите этаж</option>
            {floors?.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
          <input type="number" min={0} value={corrValue} onChange={(e) => setCorrValue(e.target.value)} placeholder="сейчас людей" />
          <button className="btn" disabled={!corrFloor || corrValue === ""} onClick={() => guarded(() => api("/api/occupancy/correct", { method: "POST", json: { floor_id: Number(corrFloor), value: Number(corrValue) } }), "Поправка применена")}>
            Применить
          </button>
        </div>
      </div>
    </>
  );
}
