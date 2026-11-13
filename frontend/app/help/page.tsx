"use client";

import { useEffect, useMemo, useState } from "react";
import { apiGet } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { ContactSupportForm } from "@/components/ContactSupportForm";
import { formatDateTime } from "@/lib/format";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useOptionalSession } from "@/lib/supabase/useOptionalSession";
import type { HelpArticleSummary, SupportRequest } from "@/types";

// The Help centre (PR-5.7, E26): every article from the approved help
// knowledge base (backend/app/support/content/), searchable with the same
// deterministic ranker Ask ORLA's support lane uses, plus the "Contact
// support" handoff. Readable signed out — the article routes are public —
// while contacting support and seeing past requests need a session.
const SEARCH_DEBOUNCE_MS = 250;

export default function HelpPage() {
  const { session, checkingSession } = useOptionalSession();
  const { businesses, businessId } = useBusinessSelector(session);

  const [articles, setArticles] = useState<HelpArticleSummary[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<HelpArticleSummary[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [requests, setRequests] = useState<SupportRequest[]>([]);

  const business = businesses.find((b) => b.id === businessId);
  const isOwner = business?.role === "owner";

  useEffect(() => {
    apiGet<HelpArticleSummary[]>("/help/articles")
      .then(setArticles)
      .catch(() => setLoadError("Could not load the help articles. Try again shortly."));
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("contact") === "1" || window.location.hash === "#contact") setContactOpen(true);
      const q = params.get("q");
      if (q) setQuery(q);
    }
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      return;
    }
    setSearching(true);
    const timer = setTimeout(() => {
      apiGet<HelpArticleSummary[]>(`/help/articles?q=${encodeURIComponent(trimmed)}`)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (!businessId) {
      setRequests([]);
      return;
    }
    apiGet<SupportRequest[]>(`/businesses/${businessId}/support/requests`)
      .then(setRequests)
      .catch(() => setRequests([]));
  }, [businessId]);

  const grouped = useMemo(() => {
    const groups: { category: string; items: HelpArticleSummary[] }[] = [];
    for (const article of articles ?? []) {
      const group = groups.find((g) => g.category === article.category);
      if (group) group.items.push(article);
      else groups.push({ category: article.category, items: [article] });
    }
    return groups;
  }, [articles]);

  return (
    <main className="wide">
      {session && <AppNav businessId={businessId || undefined} />}
      <div className="help-title-row">
        <h1>Help</h1>
        {session && businessId && (
          <button type="button" onClick={() => setContactOpen((open) => !open)} aria-expanded={contactOpen}>
            {contactOpen ? "Close" : "Contact support"}
          </button>
        )}
      </div>
      <p className="hint">
        How to use every part of ORLA. You can also ask ORLA a how-to question in{" "}
        <a href={`/chat${businessId ? `?business=${businessId}` : ""}`}>Ask ORLA</a>, for example &ldquo;How do I
        upload my stock count?&rdquo;.
      </p>

      {contactOpen && businessId && (
        <section id="contact" className="help-panel" aria-label="Contact support">
          <h2>Contact support</h2>
          <p className="hint">
            Couldn&apos;t find the answer below? Send your question to the ORLA team and they will follow up with
            you.
          </p>
          <ContactSupportForm
            businessId={businessId}
            initialQuestion={query}
            onSent={(request) => setRequests((prev) => [request, ...prev.filter((r) => r.id !== request.id)])}
          />
        </section>
      )}
      {!checkingSession && !session && (
        <p className="hint">
          <a href="/login">Log in</a> to contact ORLA support.
        </p>
      )}

      <div className="help-search">
        <label htmlFor="help-search">Search help</label>
        <input
          id="help-search"
          type="search"
          value={query}
          placeholder="e.g. upload stock count, undo import, invite staff"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      {loadError && <p className="status-error">{loadError}</p>}

      {results !== null ? (
        <section aria-label="Search results" aria-live="polite">
          <h2>{searching ? "Searching…" : `Results for “${query.trim()}”`}</h2>
          {!searching && results.length === 0 && (
            <p>
              No help articles match that.{" "}
              {session && businessId ? (
                <button type="button" onClick={() => setContactOpen(true)}>
                  Contact support
                </button>
              ) : null}
            </p>
          )}
          <ul className="help-article-list">
            {results.map((article) => (
              <ArticleItem key={article.slug} article={article} showCategory />
            ))}
          </ul>
        </section>
      ) : (
        grouped.map((group) => (
          <section key={group.category} aria-label={group.category}>
            <h2>{group.category}</h2>
            <ul className="help-article-list">
              {group.items.map((article) => (
                <ArticleItem key={article.slug} article={article} />
              ))}
            </ul>
          </section>
        ))
      )}
      {articles === null && !loadError && <p>Loading…</p>}

      {requests.length > 0 && (
        <section id="support-requests" aria-label="Support requests">
          <h2>{isOwner ? "Support requests from your business" : "Your support requests"}</h2>
          <ul className="help-request-list">
            {requests.map((r) => (
              <li key={r.id}>
                <span className={r.status === "resolved" ? "status-ok" : "status-info"}>
                  {r.status === "resolved" ? "Resolved" : "Open"}
                </span>{" "}
                — {formatDateTime(r.created_at)}
                {isOwner && <span className="hint">From {r.requester_email}</span>}
                <span className="help-request-question">{r.question}</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </main>
  );
}

function ArticleItem({ article, showCategory = false }: { article: HelpArticleSummary; showCategory?: boolean }) {
  return (
    <li>
      <a href={`/help/${article.slug}`}>
        <strong>{article.title}</strong>
      </a>
      {showCategory && <span className="hint">{article.category}</span>}
      <span className="hint">{article.summary}</span>
    </li>
  );
}
