import { apiGet } from "./client";

export interface HealthStatus {
  status: string;
  database?: string;
}

export function getHealth() {
  return apiGet<HealthStatus>("/health");
}

export function getDatabaseHealth() {
  return apiGet<HealthStatus>("/health/db");
}
