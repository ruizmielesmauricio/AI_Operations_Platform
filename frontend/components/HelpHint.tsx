"use client";

import { useId, useState } from "react";
import { TERMS, type TermKey } from "@/lib/terms";

/**
 * A small "?" that explains a term in plain English when tapped or
 * focused. Used instead of the browser's `title=` tooltips, which don't
 * exist on a phone and can't be reached with a keyboard. Text always
 * comes from lib/terms.ts, never written inline, so a wording fix
 * happens in one place.
 */
export function HelpHint({ term, text }: { term?: TermKey; text?: string }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const body = text ?? (term ? TERMS[term].hint : "");
  const name = term ? TERMS[term].label : "this";
  if (!body) return null;
  return (
    <span className="help-hint">
      <button
        type="button"
        className="help-hint__button"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`What's ${name}?`}
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setOpen(false)}
      >
        ?
      </button>
      {open && (
        <span id={id} role="note" className="help-hint__text">
          {body}
        </span>
      )}
    </span>
  );
}

/** The plain-English label for a term, followed by its "?" hint. */
export function TermLabel({ term }: { term: TermKey }) {
  return (
    <span>
      {TERMS[term].label}
      <HelpHint term={term} />
    </span>
  );
}
