"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase/client";

/**
 * Guards a page behind an active Supabase session: redirects to /login when
 * there isn't one (on load, on sign-out, and when a token refresh fails),
 * and hands back the session once confirmed. Use on any page that requires
 * auth, alongside `apiGet`/`apiPost` for the actual authorized calls.
 */
export function useRequireSession() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    if (!supabase) {
      setCheckingSession(false);
      return;
    }

    supabase.auth.getSession().then(({ data }) => {
      if (!data.session) {
        router.push("/login");
        return;
      }
      setSession(data.session);
      setCheckingSession(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, newSession) => {
      if (!newSession) {
        router.push("/login");
        return;
      }
      setSession(newSession);
    });

    return () => listener.subscription.unsubscribe();
  }, [router]);

  return { session, checkingSession };
}
