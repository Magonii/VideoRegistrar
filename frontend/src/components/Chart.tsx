import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

const BASE: EChartsOption = {
  textStyle: { fontFamily: "Inter, Segoe UI, system-ui, sans-serif" },
  grid: { left: 56, right: 48, top: 64, bottom: 32 },
  tooltip: { trigger: "axis" },
  legend: { top: 0, right: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: "#6b7686" } },
};

export const COLORS = { in: "#2f6df6", out: "#f59e0b", occupancy: "#1f9d55", wait: "#d93a3a" };

export default function Chart({
  option,
  height = 300,
  onEvents,
}: {
  option: EChartsOption;
  height?: number;
  onEvents?: Record<string, (params: unknown) => void>;
}) {
  return (
    <ReactECharts
      option={{ ...BASE, ...option }}
      style={{ height, width: "100%" }}
      notMerge
      lazyUpdate
      onEvents={onEvents}
    />
  );
}
