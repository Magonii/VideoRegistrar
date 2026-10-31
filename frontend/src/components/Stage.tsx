import { useRef, useState, type PointerEvent, type ReactNode } from "react";
import type { Pt } from "../api";

interface Props {
  src?: string;
  emptyHint?: string;
  fallbackAspect?: number;
  cursor?: string;
  onDown?: (p: Pt, e: PointerEvent) => void;
  onMove?: (p: Pt, e: PointerEvent) => void;
  onUp?: (p: Pt, e: PointerEvent) => void;
  /** Рисуется в координатах 1000 × height, ширина фиксирована, чтобы маркеры оставались круглыми. */
  children?: (w: number, h: number) => ReactNode;
}

/** Картинка (снимок камеры или план) с SVG-слоем поверх. Все события отдаются в нормализованных координатах 0..1. */
export default function Stage({ src, emptyHint, fallbackAspect = 16 / 9, cursor, onDown, onMove, onUp, children }: Props) {
  const [aspect, setAspect] = useState(fallbackAspect);
  const [failed, setFailed] = useState(false);
  const svgRef = useRef<SVGSVGElement>(null);
  const H = 1000 / aspect;

  const norm = (e: PointerEvent): Pt => {
    const r = svgRef.current!.getBoundingClientRect();
    return [Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (e.clientY - r.top) / r.height))];
  };

  return (
    <div className="stage" style={{ aspectRatio: String(aspect) }}>
      {src && !failed && (
        <img
          src={src}
          alt=""
          draggable={false}
          onLoad={(e) => {
            const { naturalWidth: w, naturalHeight: h } = e.currentTarget;
            if (w > 0 && h > 0) setAspect(w / h);
          }}
          onError={() => setFailed(true)}
        />
      )}
      {(!src || failed) && emptyHint && <div className="hint">{emptyHint}</div>}
      <svg
        ref={svgRef}
        viewBox={`0 0 1000 ${H}`}
        style={{ cursor: cursor ?? "default" }}
        onPointerDown={(e) => onDown?.(norm(e), e)}
        onPointerMove={(e) => onMove?.(norm(e), e)}
        onPointerUp={(e) => onUp?.(norm(e), e)}
      >
        {children?.(1000, H)}
      </svg>
    </div>
  );
}
