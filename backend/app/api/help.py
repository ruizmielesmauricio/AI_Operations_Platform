from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.support import (
    HelpArticleOut,
    HelpArticleSummaryOut,
    HelpSearchHitOut,
    HelpSectionOut,
)
from app.support.knowledge_base import HelpArticle, get_knowledge_base

# Public, read-only: the help articles are static product documentation
# (no tenant data), and must be readable before login — e.g. "I can't log
# in". The tenant-scoped "Contact support" routes live in app/api/support.py.
router = APIRouter(prefix="/help", tags=["help"])


def _summary(article: HelpArticle) -> dict:
    return {
        "slug": article.slug,
        "title": article.title,
        "category": article.category,
        "order": article.order,
        "summary": article.summary,
        "updated": article.updated,
    }


@router.get("/articles", response_model=list[HelpArticleSummaryOut] | list[HelpSearchHitOut])
def list_articles(q: str | None = Query(default=None, max_length=200)):
    """Every article in display order, or — with `q` — the articles that
    match it, best first, using the same deterministic ranker as the
    Ask ORLA support lane."""
    kb = get_knowledge_base()
    if q and q.strip():
        return [HelpSearchHitOut(**_summary(hit.article), score=hit.score) for hit in kb.search_articles(q)]
    return [HelpArticleSummaryOut(**_summary(article)) for article in kb.articles]


@router.get("/articles/{slug}", response_model=HelpArticleOut)
def get_article(slug: str) -> HelpArticleOut:
    article = get_knowledge_base().get(slug)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="help_article_not_found")
    return HelpArticleOut(
        **_summary(article),
        version=article.version,
        body=article.body,
        sections=[HelpSectionOut(heading=s.heading, anchor=s.anchor) for s in article.sections],
    )
