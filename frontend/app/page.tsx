import { getDatabaseHealth, getHealth } from "@/lib/api/health";

export default async function HomePage() {
  const [api, db] = await Promise.allSettled([getHealth(), getDatabaseHealth()]);

  return (
    <main>
      <h1>AI Operations Platform</h1>
      <p>Prototype skeleton — free-tier stack, same structure as production.</p>

      <h2>Connectivity check</h2>
      <ul>
        <li>
          API:{" "}
          {api.status === "fulfilled" ? (
            <span className="status-ok">reachable ({api.value.status})</span>
          ) : (
            <span className="status-error">unreachable — is the backend running?</span>
          )}
        </li>
        <li>
          Database (via API):{" "}
          {db.status === "fulfilled" ? (
            <span className="status-ok">reachable ({db.value.database})</span>
          ) : (
            <span className="status-error">unreachable — is Postgres running?</span>
          )}
        </li>
      </ul>
    </main>
  );
}
