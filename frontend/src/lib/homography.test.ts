import { describe, expect, it } from "vitest";
import { applyHomography, solveHomography } from "./homography";
import type { Pt } from "../api";

describe("solveHomography", () => {
  it("восстанавливает перспективное преобразование по четырём точкам", () => {
    const src: Pt[] = [[0.1, 0.2], [0.9, 0.15], [0.95, 0.9], [0.05, 0.85]];
    const dst: Pt[] = [[0.2, 0.1], [0.8, 0.1], [0.8, 0.9], [0.2, 0.9]];
    const h = solveHomography(src, dst);
    expect(h).not.toBeNull();
    src.forEach((p, i) => {
      const [x, y] = applyHomography(h!, p);
      expect(x).toBeCloseTo(dst[i][0], 6);
      expect(y).toBeCloseTo(dst[i][1], 6);
    });
  });

  it("возвращает null для вырожденных точек (все на одной прямой)", () => {
    const line: Pt[] = [[0, 0], [0.3, 0.3], [0.6, 0.6], [1, 1]];
    expect(solveHomography(line, line)).toBeNull();
  });
});
