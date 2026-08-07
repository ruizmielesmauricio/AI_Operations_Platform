"use client";

import { useState } from "react";
import { apiPost } from "@/lib/api/client";
import { AppNav } from "@/components/AppNav";
import { useBusinessSelector } from "@/lib/hooks/useBusinessSelector";
import { useRequireSession } from "@/lib/supabase/useRequireSession";
import type { ChatResponse } from "@/types";

// Stage E19-E24 — PR-5.6's business-data Q&A lane. Single-turn for this
// pass: each question is sent independently, with no conversation
// history resent as model context, to keep token cost down (a known,
// stated limitation — no "what about last month?" follow-up support
// yet). The thread shown here is purely a local display list; nothing
// about it is persisted server-side.
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

export default function ChatPage() {
  const { session, checkingSession } = useRequireSession();
  const { businesses, businessId, setBusinessId } = useBusinessSelector(session);

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | undefined>();

  async function handleSend() {
    const trimmed = question.trim();
    if (!trimmed || !businessId || sending) return;

    setMessages((prev) => [...prev, { role: "user", text: trimmed }]);
    setQuestion("");
    setSending(true);
    setError(undefined);

    try {
      const response = await apiPost<ChatResponse>(`/businesses/${businessId}/ai/chat`, { question: trimmed });
      setMessages((prev) => [
        ...prev,
        { role: "assistant", text: response.answer, grounded: response.grounded, links: response.links },
      ]);
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
        questions outside that scope get a plain "I can't help with that" response rather than a guess. Each
        question is independent — follow-ups like "what about last month?" aren't remembered yet.
      </p>

      {businesses.length > 1 && (
        <div>
          <label htmlFor="business">Business</label>
          <br />
          <select id="business" value={businessId} onChange={(e) => setBusinessId(e.target.value)}>
            {businesses.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="chat-thread">
        {messages.length === 0 && !sending && <p className="hint">No questions yet — try "How is my revenue doing?"</p>}
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
