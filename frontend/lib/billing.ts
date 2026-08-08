import { apiPost } from "@/lib/api/client";

/**
 * Starts Stripe Checkout for a business and redirects the browser there.
 * Shared between the onboarding page's own Subscribe button and the
 * uploads page's "subscribe to continue" prompt (shown on a 402) — both
 * need the exact same call-then-redirect, previously only implemented
 * once, inline, in app/onboarding/page.tsx.
 */
export async function redirectToCheckout(businessId: string): Promise<void> {
  const { checkout_url } = await apiPost<{ checkout_url: string }>(
    `/businesses/${businessId}/billing/checkout-session`,
    {}
  );
  window.location.href = checkout_url;
}
