import type { ReactNode } from "react";

export function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "up" | "down" | null }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className={`sub ${tone ?? ""}`}>{sub}</div>}
    </div>
  );
}

export function PageHead({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="page-head">
      <h1>{title}</h1>
      <div className="toolbar">{children}</div>
    </div>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
}) {
  return (
    <div className="seg">
      {options.map((o) => (
        <button key={o.value} className={o.value === value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, narrow }: { title: string; onClose: () => void; children: ReactNode; narrow?: boolean }) {
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${narrow ? "narrow" : ""}`}>
        <div className="modal-head">
          <h2 style={{ margin: 0, fontSize: 18 }}>{title}</h2>
          <button className="btn sm" onClick={onClose}>
            Закрыть
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export const ErrorBox = ({ message }: { message: string | null }) => (message ? <div className="error">{message}</div> : null);
