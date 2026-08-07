from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


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
