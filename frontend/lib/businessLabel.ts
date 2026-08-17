import type { Business } from "@/types";

// A branch's profile location is the clearest operational label in the
// product. Keep every branch picker and the shared company header aligned.
export function businessDisplayLabel(business: Pick<Business, "name" | "location_label">): string {
  return business.location_label?.trim() || business.name;
}
