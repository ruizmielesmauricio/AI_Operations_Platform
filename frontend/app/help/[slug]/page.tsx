"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { ApiError, apiGet } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { renderHelpMarkdown } from "@/lib/help/renderMarkdown";
import { useOptionalSession } from "@/lib/supabase/useOptionalSession";
import type { HelpArticle, HelpArticleSummary } from "@/types";

// One help article (PR-5.7, E26). Ask ORLA's support answers link here.
export default function HelpArticlePage() {
  const params = useParams<{ slug: string }>();
  const { session } = useOptionalSession();
  const { businessId } = useBusinessSelector(session);
  const [article, setArticle] = useState<HelpArticle | null>(null);
  const [allArticles, setAllArticles] = useState<HelpArticleSummary[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setArticle(null);
    setError(null);
    apiGet<HelpArticle>(`/help/articles/${encodeURIComponent(params.slug)}`)
      .then(setArticle)
      .catch((err) =>
        setError(err instanceof ApiError && err.status === 404 ? "This help article doesn't exist." : "Could not load this article.")
      );
  }, [params.slug]);

  useEffect(() => {
    apiGet<HelpArticleSummary[]>("/help/articles")
      .then(setAllArticles)
      .catch(() => setAllArticles([]));
  }, []);

  // Jump to a #section once the article has rendered (deep links from Ask ORLA).
  useEffect(() => {
    if (article && typeof window !== "undefined" && window.location.hash) {
      document.getElementById(window.location.hash.slice(1))?.scrollIntoView();
    }
  }, [article]);

  const titleToSlug = useMemo(
    () => Object.fromEntries(allArticles.filter((a) => a.slug !== article?.slug).map((a) => [a.title, a.slug])),
    [allArticles, article?.slug]
  );
  const related = allArticles.filter((a) => article && a.category === article.category && a.slug !== article.slug);

  return (
    <main className="wide">
      {session && <AppNav businessId={businessId || undefined} />}
      <p>
        <a href="/help">← All help articles</a>
      </p>
      {error && <p className="status-error">{error}</p>}
      {!article && !error && <p>Loading…</p>}
      {article && (
        <div className="help-article-layout">
          <article className="help-article">
            <span className="hint">{article.category}</span>
            <h1>{article.title}</h1>
            <p className="hint">{article.summary}</p>
            {renderHelpMarkdown(article.body, titleToSlug)}
            <p className="hint">Last updated {article.updated.split("-").reverse().join("/")}</p>
            <div className="help-panel">
              <strong>Still stuck?</strong>{" "}
              {session ? (
                <a href="/help?contact=1#contact">Contact support</a>
              ) : (
                <>
                  <a href="/login">Log in</a> to contact support.
                </>
              )}
            </div>
          </article>
          <aside className="help-article-aside" aria-label="On this page">
            <p>On this page</p>
            <nav>
              {article.sections.map((s) => (
                <a key={s.anchor} href={`#${s.anchor}`}>
                  {s.heading}
                </a>
              ))}
            </nav>
            {related.length > 0 && (
              <>
                <p>Related</p>
                <nav>
                  {related.map((a) => (
                    <a key={a.slug} href={`/help/${a.slug}`}>
                      {a.title}
                    </a>
                  ))}
                </nav>
              </>
            )}
          </aside>
        </div>
      )}
    </main>
  );
}
