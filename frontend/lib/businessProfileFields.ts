import type { BusinessProfileUpdate } from "@/types";

// Shared between frontend/app/onboarding/[id]/page.tsx (editing an
// existing business's profile, every field optional) and
// frontend/app/onboarding/page.tsx's branch-creation form (every field
// required before proceeding to payment) — one key/label list so the two
// can't silently drift apart on what "the profile" actually consists of.
//
// address_line1 is deliberately not in either list — it gets its own
// live-suggestion input (useAddressAutocomplete) in both places, rendered
// between these two lists so the on-screen field order stays exactly
// manager/contact/location, then address, then city/postal/country/
// timezone.
export const PROFILE_FIELDS_BEFORE_ADDRESS: { key: keyof BusinessProfileUpdate; label: string; type?: string }[] = [
  // Split into first/surname, not one combined field (direct request) —
  // was a single "Manager / owner name" field.
  { key: "manager_first_name", label: "Manager / owner first name" },
  { key: "manager_surname", label: "Manager / owner surname" },
  { key: "contact_email", label: "Contact email", type: "email" },
  { key: "contact_phone", label: "Contact phone" },
  { key: "location_label", label: "Location label (e.g. \"Dublin - Rathmines\")" },
];

export const PROFILE_FIELDS_AFTER_ADDRESS: { key: keyof BusinessProfileUpdate; label: string }[] = [
  { key: "city", label: "City" },
  { key: "postal_code", label: "Postal code" },
  { key: "country", label: "Country" },
  { key: "timezone", label: "Timezone" },
];
