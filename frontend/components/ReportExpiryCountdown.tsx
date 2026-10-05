"use client";

import { useEffect, useState } from "react";
import { formatExpiryCountdown } from "@/lib/format";

const EXPIRING_SOON_SECONDS = 2 * 24 * 3600;

// Live "time left" counter for a weekly OR monthly report — both stay
// available seven days after generation (ADR-019), so this one component
// serves the reports list and every report page. Starts from the
// server's own seconds_until_expiry (one authoritative clock, not each
// browser's) and ticks down locally every 30s so a page left open
// doesn't go stale. The backend still enforces expiry on every request —
// this is display only.
export function ReportExpiryCountdown({
  secondsUntilExpiry,
  variant = "inline",
}: {
  secondsUntilExpiry: number | null;
  variant?: "inline" | "banner";
}) {
  const [remaining, setRemaining] = useState(secondsUntilExpiry);

  useEffect(() => {
    setRemaining(secondsUntilExpiry);
    if (secondsUntilExpiry === null) return;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      setRemaining(Math.max(0, secondsUntilExpiry - Math.floor((Date.now() - startedAt) / 1000)));
    }, 30_000);
    return () => window.clearInterval(timer);
  }, [secondsUntilExpiry]);

  if (remaining === null) return <span>—</span>;
  const soon = remaining <= EXPIRING_SOON_SECONDS;
  const text = formatExpiryCountdown(remaining);

  if (variant === "inline") {
    return <span className={soon ? "status-warn" : undefined}>{text}</span>;
  }
  return (
    <p className={soon ? "status-warn" : "hint"} role="status">
      <strong>{text}</strong> — this report is only available for 7 days after it&apos;s generated.
      {soon ? " Download a PDF or Word copy now to keep it." : " Download a PDF or Word copy if you want to keep it."}
    </p>
  );
}
