import { redirect } from "next/navigation";

// The root URL used to be the prototype skeleton's server-side
// connectivity check. Under docker-compose that check ran inside the
// frontend container, where NEXT_PUBLIC_API_URL's localhost:8000 is the
// container itself, so it always reported the API/DB as unreachable even
// when both were healthy. The real entry point is /welcome, which already
// bounces signed-out visitors to /login and brand-new accounts to
// /onboarding. Backend health stays available at GET /health and
// /health/db.
export default function HomePage() {
  redirect("/welcome");
}
