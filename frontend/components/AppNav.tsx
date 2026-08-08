"use client";

/**
 * The first shared nav in this frontend — everything up to now
 * (frontend/app/uploads/page.tsx, frontend/app/page.tsx) has been reached
 * by direct URL, since there was only ever one real "app" page. The
 * dashboard is the second, which makes "move between app sections" a real
 * need — kept deliberately plain (text links, no styling framework) to
 * match this prototype's current minimalism rather than introducing one.
 */
export function AppNav({ businessId }: { businessId?: string }) {
  const suffix = businessId ? `?business=${businessId}` : "";
  return (
    <nav>
      <a href={`/dashboard${suffix}`}>Dashboard</a>
      {" · "}
      <a href={`/uploads${suffix}`}>Upload data</a>
      {" · "}
      <a href={`/reports${suffix}`}>Reports</a>
      {" · "}
      <a href={`/chat${suffix}`}>Ask ORLA</a>
    </nav>
  );
}
