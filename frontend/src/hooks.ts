import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Overview } from "./api";

export function useApi<T>(path: string | null, refreshMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const id = ++seq.current;
    try {
      const d = await api<T>(path);
      if (id === seq.current) {
        setData(d);
        setError(null);
      }
    } catch (e) {
      if (id === seq.current) setError((e as Error).message);
    } finally {
      if (id === seq.current) setLoading(false);
    }
  }, [path]);

  useEffect(() => {
    setLoading(true);
    void load();
    if (!refreshMs) return;
    const t = setInterval(() => void load(), refreshMs);
    return () => clearInterval(t);
  }, [load, refreshMs]);

  return { data, error, loading, reload: load };
}

/** Живая сводка по WebSocket. До первого сообщения (и при обрыве) подтягивает данные обычным запросом. */
export function useLiveOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let closed = false;

    const poll = () => api<Overview>("/api/overview").then(setData).catch(() => undefined);
    void poll();

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => setData(JSON.parse(e.data) as Overview);
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = setTimeout(connect, 3000);
      };
      ws.onerror = () => ws?.close();
    };
    connect();

    const fallback = setInterval(() => {
      if (ws?.readyState !== WebSocket.OPEN) void poll();
    }, 5000);

    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(fallback);
      ws?.close();
    };
  }, []);

  return { data, connected };
}
