"use client";

import { useState } from "react";
import { ApiError, apiPost } from "@/lib/api/client";
import type { SupportRequest } from "@/types";

/**
 * The "Contact support" handoff (PR-5.7) — used on the Help page. Ask ORLA
 * has its own one-click version of the same request (frontend/app/chat/
 * page.tsx) that sends the question the user already typed.
 */
export function ContactSupportForm({
  businessId,
  initialQuestion = "",
  onSent,
}: {
  businessId: string;
  initialQuestion?: string;
  onSent?: (request: SupportRequest) => void;
}) {
  const [question, setQuestion] = useState(initialQuestion);
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setError(null);
    try {
      const request = await apiPost<SupportRequest>(`/businesses/${businessId}/support/requests`, {
        question: trimmed,
        source: "help_page",
      });
      setSent(true);
      onSent?.(request);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send your question. Try again shortly.");
    } finally {
      setSending(false);
    }
  }

  if (sent) {
    return (
      <p className="status-ok" role="status">
        Sent to the ORLA team. They will follow up with you at your login email address.
      </p>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="help-contact-form">
      <label htmlFor="support-question">What do you need help with?</label>
      <textarea
        id="support-question"
        rows={4}
        maxLength={2000}
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="Describe what you were trying to do and what happened."
      />
      <span className="hint">
        Your question, your login email and the business it is about are sent to the ORLA team. Never include
        passwords or card details.
      </span>
      {error && <p className="status-error">{error}</p>}
      <button type="submit" disabled={sending || !question.trim()}>
        {sending ? "Sending…" : "Send to support"}
      </button>
    </form>
  );
}
