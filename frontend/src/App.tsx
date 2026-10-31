import { createContext, useContext } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import type { Overview } from "./api";
import { useLiveOverview } from "./hooks";
import Alerts from "./pages/Alerts";
import Cameras from "./pages/Cameras";
import Heatmap from "./pages/Heatmap";
import Lab from "./pages/Lab";
import OverviewPage from "./pages/Overview";
import Queues from "./pages/Queues";
import Settings from "./pages/Settings";
import Traffic from "./pages/Traffic";

const LiveContext = createContext<Overview | null>(null);
export const useLive = () => useContext(LiveContext);

const NAV = [
  { to: "/", label: "Обзор", icon: "◉", end: true },
  { to: "/traffic", label: "Трафик", icon: "▤" },
  { to: "/heatmap", label: "Тепловая карта", icon: "▦" },
  { to: "/queues", label: "Очереди", icon: "☷" },
  { to: "/alerts", label: "Оповещения", icon: "⚑" },
  { to: "/lab", label: "Мультикамера", icon: "▣" },
  { to: "/cameras", label: "Камеры", icon: "◎" },
  { to: "/settings", label: "Настройки", icon: "⚙" },
];

export default function App() {
  const { data, connected } = useLiveOverview();
  const alertCount = data?.alerts.length ?? 0;

  return (
    <LiveContext.Provider value={data}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand">
            Аналитика ТЦ<small>посетители · очереди · потоки</small>
          </div>
          <nav className="nav">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => (isActive ? "active" : "")}>
                <span>{n.icon}</span>
                {n.label}
                {n.to === "/alerts" && alertCount > 0 && <span className="badge">{alertCount}</span>}
              </NavLink>
            ))}
          </nav>
          <div className="conn">
            <span className={`dot ${connected ? "on" : ""}`} />
            {connected ? "данные в реальном времени" : "нет связи, повтор…"}
          </div>
        </aside>
        <main className="main">
          <Routes>
            <Route path="/" element={<OverviewPage />} />
            <Route path="/traffic" element={<Traffic />} />
            <Route path="/heatmap" element={<Heatmap />} />
            <Route path="/queues" element={<Queues />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/lab" element={<Lab />} />
            <Route path="/cameras" element={<Cameras />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>
    </LiveContext.Provider>
  );
}
