import type { Pt } from "../api";

export type Matrix = number[][];

/** Гомография 3x3 по четырём парам точек src[i] -> dst[i] (h33 = 1). null — точки вырождены. */
export function solveHomography(src: Pt[], dst: Pt[]): Matrix | null {
  if (src.length !== 4 || dst.length !== 4) return null;
  const n = 8;
  const a: number[][] = [];
  for (let i = 0; i < 4; i++) {
    const [x, y] = src[i];
    const [u, v] = dst[i];
    a.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
    a.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
  }
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(a[r][c]) > Math.abs(a[p][c])) p = r;
    if (Math.abs(a[p][c]) < 1e-10) return null;
    [a[c], a[p]] = [a[p], a[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = a[r][c] / a[c][c];
      for (let k = c; k <= n; k++) a[r][k] -= f * a[c][k];
    }
  }
  const h = a.map((row, i) => row[n] / row[i]);
  return [
    [h[0], h[1], h[2]],
    [h[3], h[4], h[5]],
    [h[6], h[7], 1],
  ];
}

export function applyHomography(h: Matrix, [x, y]: Pt): Pt {
  const w = h[2][0] * x + h[2][1] * y + h[2][2];
  return [(h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w];
}
