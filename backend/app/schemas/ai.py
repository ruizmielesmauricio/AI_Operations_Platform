from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
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


class ChatResponse(BaseModel):
    answer: str
    intent: str
    # False when the AI's raw answer failed the PR-5.3 grounding
    # guardrail and `answer` is a safe fallback message instead — the
    # frontend can use this to render a slightly different (not alarming)
    # style for the fallback case.
    grounded: bool
    # A fixed, small set of app pages ("dashboard", "reports") the answer
    # references — the frontend renders these as real, safe <a> elements
    # itself. Never arbitrary text/URLs sourced from the model.
    links: list[str] = []
