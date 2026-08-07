// Chart option builders, extracted from frontend/app/dashboard/page.tsx so
// frontend/app/reports/[id]/page.tsx reuses the exact same chart
// definitions (per Stage D17/D18's plan: "no new chart infrastructure").
import type { EChartsOption } from "echarts";
import type { DailyForecast, ProductMarginRow, StockCoverRow } from "@/types";

// Direct request: show each product's category beside its name — for a
// chart's category-axis label, that means appending it to the label text
// itself (no separate column to add, unlike a table row).
function _labelWithCategory(name: string, categoryName: string | null | undefined): string {
  return categoryName ? `${name} (${categoryName})` : name;
}

export function marginBarOption(rows: ProductMarginRow[], title: string): EChartsOption {
  const sorted = [...rows].sort((a, b) => Number(a.gross_profit) - Number(b.gross_profit));
  return {
    title: { text: title, textStyle: { fontSize: 13 } },
    grid: { left: 140, right: 30, top: 40, bottom: 20 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value" },
    yAxis: { type: "category", data: sorted.map((r) => _labelWithCategory(r.name, r.category_name)) },
    series: [
      {
        type: "bar",
        data: sorted.map((r) => {
          const value = Number(r.gross_profit);
          return { value, itemStyle: { color: value < 0 ? "#cf222e" : "#1a7f37" } };
        }),
      },
    ],
  };
}

export function revenueForecastLineOption(daily: DailyForecast[]): EChartsOption {
  const dates = daily.map((d) => d.forecast_date);
  return {
    grid: { left: 70, right: 30, top: 20, bottom: 30 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "category", data: dates },
    yAxis: { type: "value", name: "€" },
    series: [
      { name: "Typical low", type: "line", data: daily.map((d) => Number(d.low)), lineStyle: { type: "dashed", color: "#8c959f" }, symbol: "none" },
      { name: "Forecast", type: "line", data: daily.map((d) => Number(d.point)), lineStyle: { color: "#0969da", width: 2 }, symbol: "circle" },
      { name: "Typical high", type: "line", data: daily.map((d) => Number(d.high)), lineStyle: { type: "dashed", color: "#8c959f" }, symbol: "none" },
    ],
  };
}

export function stockCoverBarOption(rows: StockCoverRow[]): EChartsOption {
  const sorted = [...rows]
    .sort((a, b) => Number(a.cover_days) - Number(b.cover_days))
    .slice(0, 15);
  return {
    grid: { left: 140, right: 30, top: 20, bottom: 20 },
    tooltip: { trigger: "axis" },
    xAxis: { type: "value", name: "Days of stock left" },
    yAxis: { type: "category", data: sorted.map((r) => _labelWithCategory(r.name, r.category_name)) },
    series: [
      {
        type: "bar",
        data: sorted.map((r) => {
          const value = Number(r.cover_days);
          return { value, itemStyle: { color: value <= 7 ? "#cf222e" : "#0969da" } };
        }),
      },
    ],
  };
}
