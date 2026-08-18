"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api/client";
import { supabase } from "@/lib/supabase/client";
import type { Member } from "@/types";

export interface CurrentMemberIdentity {
  firstName: string | null;
  surname: string | null;
  role: string | null;
  email: string | null;
  // Ready-to-render "First Last (role)" (falling back to the account's
  // own email, then a generic "Account") — the exact label AppNav has
  // always shown, kept here so both callers render identically.
  label: string | null;
}

/**
 * Resolves the signed-in user's own name/role for `businessId`, by
 * cross-referencing `supabase.auth.getUser()` against the business's own
 * membership list — never guessed from Supabase auth metadata alone, so
 * the role shown is always accurate for both owners and staff. Extracted
 * from frontend/components/AppNav.tsx's own original inline effect, once
 * frontend/app/welcome/page.tsx needed the identical resolution a second
 * time — the same "the second caller is the point to share it" threshold
 * frontend/lib/hooks/useBusinessSelector.ts's own docstring already used.
 */
export function useCurrentMember(businessId: string | undefined): CurrentMemberIdentity {
  const [identity, setIdentity] = useState<CurrentMemberIdentity>({
    firstName: null,
    surname: null,
    role: null,
    email: null,
    label: null,
  });

  useEffect(() => {
    if (!businessId || !supabase) {
      setIdentity({ firstName: null, surname: null, role: null, email: null, label: null });
      return;
    }
    let active = true;
    Promise.all([supabase.auth.getUser(), apiGet<Member[]>(`/businesses/${businessId}/members`)])
      .then(([{ data }, members]) => {
        if (!active) return;
        const email = data.user?.email ?? null;
        const member = members.find((item) => item.user_id === data.user?.id);
        if (!member) {
          setIdentity({ firstName: null, surname: null, role: null, email, label: email });
          return;
        }
        const name = `${member.first_name} ${member.surname}`.trim() || email || "Account";
        setIdentity({
          firstName: member.first_name || null,
          surname: member.surname || null,
          role: member.role,
          email,
          label: `${name} (${member.role})`,
        });
      })
      .catch(() => {
        if (active) setIdentity({ firstName: null, surname: null, role: null, email: null, label: null });
      });
    return () => {
      active = false;
    };
  }, [businessId]);

  return identity;
}
