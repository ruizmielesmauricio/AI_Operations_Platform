// Shared layout primitives, extracted from frontend/app/dashboard/page.tsx
// so frontend/app/reports/[id]/page.tsx renders sections/stats identically
// rather than duplicating the markup.
import type { ReactNode } from "react";
import type { Finding, Recommendation } from "@/types";
import { severityClass } from "@/lib/format";
import { findingKey } from "@/lib/findings";
import { HelpHint } from "@/components/HelpHint";
import { TERMS, type TermKey } from "@/lib/terms";

export function Section({
  title,
  children,
  id,
  hint,
}: {
  title: ReactNode;
  // Glossary key: adds a tappable "?" explanation beside the heading.
  hint?: TermKey;
  children: ReactNode;
  // Optional anchor target for a page-level table of contents (reports
  // page only — the dashboard has no TOC, so its callers just omit this).
  id?: string;
}) {
  return (
    <section id={id}>
      <h2>
        {title}
        {hint && <HelpHint term={hint} />}
      </h2>
      {children}
    </section>
  );
}

export function Stat({
  term,
  label,
  value,
  title,
  trendPct,
  trendLabel = "previous period",
  note,
  noteTitle,
}: {
  // A glossary key (lib/terms.ts): shows the plain-English name plus a
  // tappable "?" explanation. `label`/`title` remain for stats with a
  // dynamic name (e.g. "Expected sales, next 7 days").
  term?: TermKey;
  label?: string;
  value: string;
  title?: string;
  trendPct?: string | null;
  // What "previous period" means concretely — the dashboard's date range
  // is user-chosen so "previous period" (the immediately preceding range
  // of equal length) is the most specific true statement available, but
  // a report's comparison window is always exactly last week or last
  // month, so callers there should pass that instead of leaving it vague.
  trendLabel?: string;
  note?: string;
  noteTitle?: string;
}) {
  return (
    <div>
      {term ? (
        <span>
          {TERMS[term].label}
          <HelpHint term={term} />
        </span>
      ) : (
        <span title={title}>{label}</span>
      )}
      : <strong>{value}</strong>
      {trendPct !== undefined && trendPct !== null && (
        <span className={Number(trendPct) >= 0 ? "status-ok" : "status-error"}>
          {" "}
          ({Number(trendPct) >= 0 ? "+" : ""}
          {trendPct}% vs {trendLabel})
        </span>
      )}
      {note && <span title={noteTitle}> — {note}</span>}
    </div>
  );
}

// Direct request: show each product's category beside its name in every
// product-row table, on both the dashboard and reports pages — a small
// muted inline label, never its own column (most products have none yet,
// so a dedicated column would be mostly empty).
export function CategoryLabel({ name }: { name: string | null | undefined }) {
  if (!name) return null;
  return <span style={{ color: "var(--muted-fg, #666)", fontSize: "0.85em" }}> · {name}</span>;
}

// Shared between the dashboard's Findings & Recommendations section and
// the report's Action Plan section — same list rendering, same
// finding-message pairing (which is what actually names the specific
// product; rec.title/rec.description alone never do).
export function RecommendationList({
  recommendations,
  findingByKey,
  showCategory,
}: {
  recommendations: Recommendation[];
  findingByKey: Map<string, Finding>;
  showCategory: boolean;
}) {
  return (
    <ul>
      {recommendations.map((rec, index) => {
        const finding = findingByKey.get(findingKey(rec.finding_type, rec.evidence));
        const categoryName = rec.evidence.category_name as string | null | undefined;
        return (
          <li key={index} className={severityClass(rec.severity)}>
            <strong>{rec.title}</strong>
            {showCategory && categoryName && <CategoryLabel name={categoryName} />}
            {finding && <> — {finding.message}</>}
            <br />
            <span>{rec.description}</span>
          </li>
        );
      })}
    </ul>
  );
}
