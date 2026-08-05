"use client";

import ReactECharts from "echarts-for-react";
import type { EChartsOption } from "echarts";

/**
 * Thin wrapper around echarts-for-react (ADR-010: charts render in the
 * browser from structured API payloads, never server-rendered images) —
 * one place chart sizing/theming lives so individual dashboard sections
 * don't each reinvent it.
 */
export function Chart({ option, height = 320 }: { option: EChartsOption; height?: number }) {
  return <ReactECharts option={option} style={{ height, width: "100%" }} notMerge lazyUpdate />;
}
