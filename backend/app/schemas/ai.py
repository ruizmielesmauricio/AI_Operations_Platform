from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    # Direct request: combine every branch in this business's group into
    # one answer instead of reading business_id alone — reuses
    # app/application/business_group.py exactly as the dashboard's own
    # "Combine all branches" checkbox does. A question that names one
    # specific branch by itself still overrides this for that turn (see
    # app/ai/service.py's deterministic branch-name detection) — an
    # explicit mention is always more specific than a blanket toggle.
    all_branches: bool = False
    # Last-exchange-only conversation memory — the frontend resends just
    # the immediately preceding question/answer, never the whole thread,
    # to keep per-request token cost bounded (a deliberate scope choice,
    # see app/ai/service.py::answer_question's own docstring). Both None
    # on the first question of a session. Trimmed together, not
    # independently required — a lone previous_question with no
    # previous_answer (or vice versa) is treated as "no prior exchange"
    # by answer_question, since both branches there check `if
    # previous_question and previous_answer`.
    previous_question: str | None = Field(default=None, max_length=1000)
    previous_answer: str | None = Field(default=None, max_length=4000)
    # The previous turn's own ChatResponse.intent, echoed straight back —
    # untrusted client input, never used directly by answer_question
    # (only ever checked against a fixed allow-list before being used to
    # deterministically recover an unresolved follow-up question). A
    # generous max_length rather than one tied to today's longest real
    # intent name — this is a plain string field, not parsed as an enum
    # at the schema layer, so the real validation happens in
    # app/ai/service.py where the actual allow-list lives.
    previous_intent: str | None = Field(default=None, max_length=50)
    # Every intent from the previous turn's own ChatResponse.intents,
    # echoed straight back — same untrusted-input posture as
    # previous_intent above (only ever checked against a fixed allow-list
    # in app/ai/service.py, never used directly). Lets a follow-up after
    # a multi-intent previous answer recover against any part of it, not
    # just the first. Optional/empty for an ordinary single-intent
    # previous turn — previous_intent alone already covers that case.
    previous_intents: list[str] | None = Field(default=None, max_length=3)


class ChatResponse(BaseModel):
    answer: str
    # The first (or only) sub-question's intent — kept singular so an
    # existing caller reading this one field keeps working unchanged even
    # for a multi-intent answer. See `intents` below for the full list.
    intent: str
    # False when the AI's raw answer failed the PR-5.3 grounding
    # guardrail and `answer` is a safe fallback message instead — the
    # frontend can use this to render a slightly different (not alarming)
    # style for the fallback case. For a multi-intent answer, False means
    # at least one part fell back this way; the other parts may still be
    # fully answered within `answer`.
    grounded: bool
    # A fixed, small set of app pages ("dashboard", "reports") the answer
    # references — the frontend renders these as real, safe <a> elements
    # itself. Never arbitrary text/URLs sourced from the model.
    links: list[str] = []
    # Every sub-question's intent, in question order — length 1 for an
    # ordinary single-intent question (matching `intent` above), longer
    # for a compound one ("what's my revenue and what should I reorder").
    # Echo this back as the next request's previous_intents.
    intents: list[str] = []
