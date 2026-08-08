"use client";

import { useEffect, useState } from "react";
import { apiPost } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { ChatResponse } from "@/types";

// Stage E19-E24 — PR-5.6's business-data Q&A lane. Last-exchange-only
// memory: each question resends just the immediately preceding
// question/answer as conversation context, never the whole thread, to
// keep per-request token cost bounded (a deliberate scope choice, see
// app/ai/service.py::answer_question's own docstring) — a follow-up like
// "what about last month?" now resolves correctly, but ORLA still has no
// memory of anything further back than one exchange. The thread shown
// here is purely a local display list; nothing about it is persisted
// server-side.
interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  grounded?: boolean;
  links?: string[];
}

// The only two pages `links` can ever reference (app/schemas/ai.py's
// ChatResponse — a fixed enum, never an arbitrary URL from the model).
// Kept out of the message text itself and rendered as real anchors here
// so nothing derived from AI-generated text is ever treated as HTML.
const LINK_TARGETS: Record<string, { label: string; path: string }> = {
  dashboard: { label: "Dashboard", path: "/dashboard" },
  reports: { label: "Reports", path: "/reports" },
};

// The dropdown's sentinel value for "combine every branch" — never a real
// business id, so it can share one <select> with the real business
// options below rather than needing a second control.
const ALL_BRANCHES_VALUE = "__all_branches__";

export default function ChatPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | undefined>();
  // Direct request: an "All branches" option alongside individual
  // businesses. businessId still names which group to resolve from (the
  // backend's group resolution is symmetric — any member's id works, see
  // app/application/business_group.py), this flag is the only thing that
  // actually changes what gets sent.
  const [allBranches, setAllBranches] = useState(false);
  // Last-exchange-only memory — tracked separately from the displayed
  // `messages` thread (which may also hold an error state) so exactly
  // one real question/answer pair is ever resent as context, per the
  // scope decision above. Reset whenever the selected business or the
  // all-branches toggle changes: a different scope has entirely
  // different data, so a prior exchange from elsewhere would be actively
  // wrong to carry into it, not just stale.
  const [lastExchange, setLastExchange] = useState<{ question: string; answer: string; intent: string } | null>(null);

  useEffect(() => {
    setLastExchange(null);
  }, [businessId, allBranches]);

  function handleSelectorChange(value: string) {
    if (value === ALL_BRANCHES_VALUE) {
      setAllBranches(true);
    } else {
      setAllBranches(false);
      setBusinessId(value);
    }
  }

  async function handleSend() {
    const trimmed = question.trim();
    if (!trimmed || !businessId || sending) return;

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setQuestion("");
    setSending(true);
    setError(undefined);

    try {
      const response = await apiPost<ChatResponse>(`/businesses/${businessId}/ai/chat`, {
        question: trimmed,
        all_branches: allBranches,
        previous_question: lastExchange?.question,
        previous_answer: lastExchange?.answer,
        previous_intent: lastExchange?.intent,
      });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: response.answer, grounded: response.grounded, links: response.links },
      ]);
      setLastExchange({ question: trimmed, answer: response.answer, intent: response.intent });
    } catch {
      setError("Could not reach the assistant. Your dashboard and reports are unaffected — try again shortly.");
    } finally {
      setSending(false);
    }
  }

  if (checkingSession) {
    return (
      <main>
        <p>Checking session…</p>
      </main>
    );
  }

  if (!session) {
    return (
      <main>
        <p>Supabase is not configured yet — set NEXT_PUBLIC_SUPABASE_URL/ANON_KEY in frontend/.env.local.</p>
      </main>
    );
  }

  if (businesses.length === 0) {
    return (
      <main>
        <h1>Ask ORLA</h1>
        <p>
          No business yet — <a href="/onboarding">create one first</a>.
        </p>
      </main>
    );
  }

  return (
    <main className="wide">
      <AppNav businessId={businessId} />
      <h1>Ask ORLA</h1>
      <p className="hint">
        ORLA can answer questions about your revenue, retail or workshop performance, forecast, recommendations, or
        your latest report. Not a general chatbot — answers are grounded only in your own calculated data, and
        questions outside that scope get a plain "I can't help with that" response rather than a guess. ORLA
        remembers your last question and answer, so a follow-up like "what about the previous period?" works —
        but only one exchange back, not the whole conversation.
      </p>

      {businesses.length > 1 && (
        <div>
          <label htmlFor="business">Business</label>
          <br />
          <select
            id="business"
            value={allBranches ? ALL_BRANCHES_VALUE : businessId}
            onChange={(e) => handleSelectorChange(e.target.value)}
          >
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
            <option value={ALL_BRANCHES_VALUE}>All branches</option>
          </select>
          {/* A question can still name one specific branch by itself
              (e.g. "revenue at Galway last week?") and ORLA answers about
              that branch regardless of what's selected here — see
              app/ai/service.py's deterministic branch-name detection. */}
          <span className="hint"> Or just name a branch in your question — ORLA understands either way.</span>
        </div>
      )}

      <div className="chat-thread">
        {messages.length === 0 && !sending && (
          <p className="hint">
            <strong>ORLA:</strong> Hello, I&apos;m ORLA — Operational Reporting and Logic Analytics.
            {businesses.length > 1
              ? " Which branch would you like information about? Pick one above, or just name it in your question."
              : ' Try asking something like "How is my revenue doing?"'}
          </p>
        )}
        {messages.map((m, i) => (
          <p
            key={i}
            className={m.role === "user" ? "chat-user" : m.grounded === false ? "chat-assistant status-warn" : "chat-assistant"}
            style={{ whiteSpace: "pre-wrap" }}
          >
            <strong>{m.role === "user" ? "You" : "ORLA"}:</strong> {m.text}
            {m.links && m.links.length > 0 && (
              <>
                {" "}
                {m.links.map((link, j) => {
                  const target = LINK_TARGETS[link];
                  if (!target) return null;
                  return (
                    <span key={link}>
                      {j > 0 && " · "}
                      <a href={`${target.path}?business=${businessId}`}>{target.label} →</a>
                    </span>
                  );
                })}
              </>
            )}
          </p>
        ))}
        {sending && (
          <p className="hint">
            <strong>ORLA:</strong> Thinking…
          </p>
        )}
      </div>

      {error && <p className="status-error">{error}</p>}

      <div>
        <input
          type="text"
          value={question}
          placeholder="Ask a question about your business…"
          disabled={sending}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
          style={{ width: "70%" }}
        />{" "}
        <button type="button" onClick={handleSend} disabled={sending || !question.trim()}>
          Send
        </button>
      </div>
    </main>
  );
}
