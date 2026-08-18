"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AppNav } from "@/components/AppNav";
import { severityClass } from "@/lib/format";
import { apiGet } from "@/lib/api/client";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useCurrentMember } from "@/lib/hooks/useCurrentMember";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { Findings } from "@/types";

// The new post-login landing — direct request, found missing during a
// gap review: both login paths (password and Google OAuth,
// frontend/app/login/page.tsx) used to send every login straight to
// /onboarding regardless of whether this was a brand-new signup or a
// returning owner/staff member. That page's own create-business form is
// already correctly gated to genuinely-new accounts, but there was no
// welcome message anywhere (grepped the whole frontend for "welcome" —
// zero matches) and no differentiated landing at all. This page is that
// landing: a welcome message naming the signed-in user, a preview of
// their newest findings, and a way straight into the Dashboard — a
// brand-new account with no business yet is bounced straight to
// /onboarding below instead, since there's nothing here yet worth
// welcoming them to.
const MAX_FINDINGS_PREVIEW = 5;

export default function WelcomePage() {
  const router = useRouter();
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, loaded: businessesLoaded } = useBusinessSelector(session);
  const { firstName } = useCurrentMember(businessId);

  const [findings, setFindings] = useState<Findings | null>(null);
  const [findingsError, setFindingsError] = useState<string | null>(null);

  // A genuinely new account (zero businesses) has nothing here worth
  // welcoming them to — send them straight to the existing, already-
  // correctly-gated create-business flow instead. Waits for
  // businessesLoaded so this never flash-redirects an account that does
  // have a business, which briefly renders as an empty list too before
  // the fetch resolves.
  useEffect(() => {
    if (businessesLoaded && businesses.length === 0) {
      router.push("/onboarding");
    }
  }, [businessesLoaded, businesses, router]);

  useEffect(() => {
    if (!businessId) return;
    apiGet<Findings>(`/businesses/${businessId}/analytics/findings`)
      .then(setFindings)
      .catch(() => setFindingsError("Could not load findings."));
  }, [businessId]);

  if (checkingSession) {
    return (
      <main>
        <p>Checking session…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <main>
        <p>Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.</p>
      </main>
    );
  }

  if (!businessesLoaded) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  if (businesses.length === 0) {
    // Redirect already fired above; nothing meaningful to render while
    // the browser navigates away.
    return null;
  }

  const preview = findings?.findings.slice(0, MAX_FINDINGS_PREVIEW) ?? [];
  const remaining = findings ? findings.findings.length - preview.length : 0;

  return (
    <main>
      <AppNav businessId={businessId} />
      <h1>{firstName ? `Welcome back, ${firstName}` : "Welcome back"}</h1>
      <p className="hint">Here's a quick look at what's new — check the full picture on your Dashboard.</p>

      <h2>Newest findings</h2>
      {findingsError && <p className="status-error">{findingsError}</p>}
      {!findingsError && !findings && <p>Loading…</p>}
      {!findingsError && findings && preview.length === 0 && (
        <p>
          No findings yet — <a href={`/uploads${businessId ? `?business=${businessId}` : ""}`}>upload your data</a> to
          get started.
        </p>
      )}
      {preview.length > 0 && (
        <ul>
          {preview.map((finding, i) => (
            <li key={`${finding.rule_id}-${i}`} className={severityClass(finding.severity)}>
              {finding.message}
            </li>
          ))}
        </ul>
      )}
      {remaining > 0 && <p className="hint">…and {remaining} more on the Dashboard.</p>}

      <p>
        <button type="button" onClick={() => router.push(`/dashboard${businessId ? `?business=${businessId}` : ""}`)}>
          Go to your Dashboard
        </button>
      </p>
    </main>
  );
}
