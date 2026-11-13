import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class HelpArticleSummaryOut(BaseModel):
    slug: str
    title: str
    category: str
    order: int
    summary: str
    updated: str


class HelpSearchHitOut(HelpArticleSummaryOut):
    score: float


class HelpSectionOut(BaseModel):
    heading: str
    anchor: str


class HelpArticleOut(HelpArticleSummaryOut):
    version: int
    # Markdown body. The frontend renders it with its own small, safe
    # renderer (no raw HTML) — see frontend/lib/help/renderMarkdown.tsx.
    body: str
    sections: list[HelpSectionOut]


class SupportRequestCreate(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    source: Literal["chat", "help_page"] = "help_page"
    # Context from Ask ORLA when the handoff came from the chat — optional,
    # untrusted (slugs are re-validated against the knowledge base).
    orla_answer: str | None = Field(default=None, max_length=4000)
    article_slugs: list[str] | None = Field(default=None, max_length=5)


class SupportRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question: str
    source: str
    status: str
    requester_email: str
    article_slugs: list[str] | None
    created_at: datetime
    resolved_at: datetime | None
