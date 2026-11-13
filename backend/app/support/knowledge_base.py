"""The approved help knowledge base (PR-5.7, ADR-020, ADR-028).

Articles live in ``app/support/content/*.md`` as Markdown with a small
front-matter block::

    ---
    slug: upload-stock-count
    title: Upload your stock count
    category: Uploading data
    order: 12
    summary: One sentence shown in lists and search results.
    keywords: [stock take, inventory, ...]
    version: 1
    updated: 2026-11-13
    ---

Each ``## Heading`` section of an article is one retrievable passage.
Retrieval is a deterministic, field-weighted BM25 ranker over those
passages — no embeddings, no AI call, no network — so the same question
always retrieves the same passages, it is unit-testable, and it costs
nothing per question. The support lane (app/ai/support_lane.py) may only
ever answer from passages this module returns, and the Help page's
search uses the very same ranker.

Loaded once per process (lru_cache); content changes ship as code
changes, never at runtime.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

CONTENT_DIR = Path(__file__).parent / "content"

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_REQUIRED_FIELDS = ("slug", "title", "category", "summary", "version", "updated")

# Field weights for the ranker: a query word in a section heading or the
# article's own curated keywords says far more about relevance than one
# buried in a paragraph.
_WEIGHT_TEXT = 1.0
_WEIGHT_HEADING = 2.5
_WEIGHT_TITLE = 2.0
_WEIGHT_KEYWORDS = 2.5
_BM25_K1 = 1.2
_BM25_B = 0.6
# A curated multi-word keyword ("stock count", "generate reports now")
# found verbatim in the question is a strong, cheap signal — added on top
# of the per-word score for every passage of that article.
_PHRASE_BONUS = 3.0

# Below this, the best passage is not considered to answer the question:
# the support lane refuses and offers a human handoff instead of letting
# the model improvise. Calibrated against tests/unit/test_support_
# knowledge_base.py's real how-to and off-topic questions.
MIN_CONFIDENT_SCORE = 6.0
# Short questions ("what is the pilot?") have one or two meaningful words,
# so their absolute score is naturally low. They still count as confident
# when the best passage contains every one of those words and clears this
# lower floor.
MIN_FULLY_COVERED_SCORE = 4.0
# Passages scoring below this fraction of the best one are dropped, so a
# strong match is not padded out with loosely related text.
_RELATIVE_CUTOFF = 0.45

_STOPWORDS = frozenset(
    """
    a about above after again all also am an and any are as at be been before being below between both but by
    can could did do does doing done down during each either else even ever every few for from further get gets
    got had has have having he her here hers him his how i if in into is it its itself just let lets like me
    might more most much must my myself no nor not now of off on once one only or other our ours out over own
    please same shall she should so some such than that the their theirs them then there these they this those
    through to too under until up upon us very want was we were what when where which while who whom why will
    with would you your yours yourself orla i'm im ive i've dont don't cant can't won't isnt isn't doesnt doesn't
    """.split()
)

# Plain-language variants mapped onto the words the articles use, so
# "stocktake" finds "stock count" and "log on" finds "log in". Applied to
# both queries and content, so it can only ever add recall, never invent
# content.
_SYNONYMS = {
    "stocktake": ("stock", "count"),
    "stocktaking": ("stock", "count"),
    "inventory": ("stock",),
    "signin": ("log", "in"),
    "login": ("log", "in"),
    "logon": ("log", "in"),
    "signup": ("sign", "up"),
    "register": ("sign", "up"),
    "colleague": ("employee",),
    "colleagues": ("employee",),
    "worker": ("employee",),
    "workers": ("employee",),
    "staff": ("staff", "employee"),
    "excel": ("excel", "xlsx"),
    "spreadsheet": ("spreadsheet", "xlsx", "csv"),
    "cancelled": ("cancel",),
    "canceled": ("cancel",),
    "unsubscribe": ("cancel", "subscription"),
    "location": ("location", "branch"),
    "store": ("store", "shop"),
    "delete": ("delete", "remove"),
    "revert": ("undo",),
    "reverse": ("reverse", "undo"),
    "rollback": ("undo",),
    "threshold": ("threshold", "reorder", "point"),
    "thresholds": ("threshold", "reorder", "point"),
    "invitation": ("invite",),
    "docx": ("docx", "word"),
    "human": ("human", "support"),
    "contact": ("contact", "support"),
}

_WORD_PATTERN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
# Words skipped when matching an article's key phrases against a question
# (see KnowledgeBase._score_passages).
_PHRASE_FILLER_WORDS = frozenset({"my", "our", "your", "the", "a", "an", "their", "this", "these", "those", "all"})


def _strip_suffix(word: str) -> str:
    if len(word) >= 6 and word.endswith("ing"):
        return word[:-3]
    if len(word) >= 5 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) >= 5 and word.endswith("ed"):
        return word[:-2]
    if len(word) >= 5 and word.endswith(("xes", "ches", "shes", "sses")):
        return word[:-2]
    if len(word) >= 4 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def _stem(word: str) -> str:
    """Light, deterministic suffix stripping — enough that "uploads",
    "uploaded" and "uploading" meet "upload", and "create"/"created" or
    "price"/"pricing" meet each other (a trailing "e" is dropped from every
    longer stem, symmetrically for content and queries). No dependency."""
    stem = _strip_suffix(word)
    if len(stem) > 4 and stem.endswith("e"):
        stem = stem[:-1]
    return stem


def tokenize(text: str) -> list[str]:
    """Lower-cased, stop-word-free, stemmed tokens (with synonym
    expansion). Shared by indexing, querying and the support-answer
    grounding check so all three agree on what a "word" is."""
    tokens: list[str] = []
    for raw in _WORD_PATTERN.findall(text.lower().replace("’", "'")):
        if raw in _STOPWORDS:
            continue
        expansions = _SYNONYMS.get(raw)
        words = expansions if expansions else (raw,)
        for word in words:
            if word in _STOPWORDS or len(word) < 2:
                continue
            tokens.append(_stem(word))
    return tokens


def _normalise_phrase(text: str) -> str:
    return " ".join(_WORD_PATTERN.findall(text.lower().replace("’", "'")))


@dataclass(frozen=True)
class HelpSection:
    article_slug: str
    heading: str
    anchor: str
    text: str

    @property
    def passage_id(self) -> str:
        return f"{self.article_slug}#{self.anchor}"


@dataclass(frozen=True)
class HelpArticle:
    slug: str
    title: str
    category: str
    order: int
    summary: str
    keywords: tuple[str, ...]
    version: int
    updated: str
    body: str
    sections: tuple[HelpSection, ...]


@dataclass(frozen=True)
class RetrievedPassage:
    passage_id: str
    article_slug: str
    article_title: str
    heading: str
    text: str
    score: float
    # Share of the question's distinct meaningful words found in this
    # passage (or its article's title/keywords), 0..1.
    coverage: float = 0.0


@dataclass(frozen=True)
class ArticleHit:
    article: HelpArticle
    score: float


class HelpContentError(ValueError):
    """Raised at load time for a malformed article — fails loudly (and in
    tests) rather than silently dropping a help page."""


def _parse_front_matter(raw: str, path: Path) -> tuple[dict[str, object], str]:
    text = raw.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise HelpContentError(f"{path.name}: missing front-matter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise HelpContentError(f"{path.name}: unterminated front-matter")
    meta: dict[str, object] = {}
    for line in text[4:end].split("\n"):
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise HelpContentError(f"{path.name}: bad front-matter line {line!r}")
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            meta[key.strip()] = tuple(v.strip() for v in value[1:-1].split(",") if v.strip())
        else:
            meta[key.strip()] = value
    return meta, text[end + len("\n---\n"):].strip()


def _anchor(heading: str) -> str:
    return "-".join(re.findall(r"[a-z0-9]+", heading.lower())) or "section"


def _split_sections(slug: str, body: str) -> tuple[HelpSection, ...]:
    sections: list[HelpSection] = []
    heading: str | None = None
    lines: list[str] = []
    for line in body.split("\n"):
        if line.startswith("## "):
            if heading is not None:
                sections.append(HelpSection(slug, heading, _anchor(heading), "\n".join(lines).strip()))
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    if heading is not None:
        sections.append(HelpSection(slug, heading, _anchor(heading), "\n".join(lines).strip()))
    return tuple(sections)


def _load_article(path: Path) -> HelpArticle:
    meta, body = _parse_front_matter(path.read_text(encoding="utf-8"), path)
    missing = [f for f in _REQUIRED_FIELDS if not meta.get(f)]
    if missing:
        raise HelpContentError(f"{path.name}: missing {', '.join(missing)}")
    slug = str(meta["slug"])
    if not _SLUG_PATTERN.match(slug) or path.stem != slug:
        raise HelpContentError(f"{path.name}: slug {slug!r} must be kebab-case and match the file name")
    sections = _split_sections(slug, body)
    if not sections:
        raise HelpContentError(f"{path.name}: needs at least one '## ' section")
    keywords = meta.get("keywords") or ()
    return HelpArticle(
        slug=slug,
        title=str(meta["title"]),
        category=str(meta["category"]),
        order=int(str(meta.get("order") or 999)),
        summary=str(meta["summary"]),
        keywords=tuple(keywords) if isinstance(keywords, tuple) else (str(keywords),),
        version=int(str(meta["version"])),
        updated=str(meta["updated"]),
        body=body,
        sections=sections,
    )


@dataclass(frozen=True)
class _IndexedPassage:
    section: HelpSection
    article: HelpArticle
    weighted_tf: dict[str, float]
    length: float


class KnowledgeBase:
    def __init__(self, articles: list[HelpArticle]):
        slugs = [a.slug for a in articles]
        if len(slugs) != len(set(slugs)):
            raise HelpContentError("duplicate article slug")
        self.articles: tuple[HelpArticle, ...] = tuple(sorted(articles, key=lambda a: (a.order, a.title)))
        self._by_slug = {a.slug: a for a in self.articles}
        self._passages: list[_IndexedPassage] = []
        for article in self.articles:
            title_tokens = tokenize(article.title)
            keyword_tokens = tokenize(" ".join(article.keywords))
            for section in article.sections:
                tf: Counter[str] = Counter()
                for token in tokenize(section.text):
                    tf[token] += _WEIGHT_TEXT
                for token in tokenize(section.heading):
                    tf[token] += _WEIGHT_HEADING
                for token in title_tokens:
                    tf[token] += _WEIGHT_TITLE
                for token in keyword_tokens:
                    tf[token] += _WEIGHT_KEYWORDS
                self._passages.append(_IndexedPassage(section, article, dict(tf), sum(tf.values())))
        n = len(self._passages)
        self._avg_len = (sum(p.length for p in self._passages) / n) if n else 1.0
        df: Counter[str] = Counter()
        for p in self._passages:
            df.update(p.weighted_tf.keys())
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self._phrases_by_slug = {
            a.slug: tuple(_normalise_phrase(k) for k in a.keywords if " " in k.strip()) for a in self.articles
        }

    def get(self, slug: str) -> HelpArticle | None:
        return self._by_slug.get(slug)

    def passage(self, passage_id: str) -> HelpSection | None:
        slug, _, anchor = passage_id.partition("#")
        article = self._by_slug.get(slug)
        if article is None:
            return None
        return next((s for s in article.sections if s.anchor == anchor), None)

    def _score_passages(self, query: str) -> list[tuple[float, _IndexedPassage]]:
        query_tokens = set(tokenize(query))
        if not query_tokens:
            return []
        normalised_query = f" {_normalise_phrase(query)} "
        # Found by the ORLA-91 eval: "how do I upload sales?" matched the
        # "upload sales" phrase but "how do I upload my sales?" did not, and
        # fell below the confidence floor (refused with a handoff). A
        # possessive/determiner between a phrase's words never changes what
        # is being asked, so phrases are also tried with those removed.
        compact_query = " " + " ".join(w for w in normalised_query.split() if w not in _PHRASE_FILLER_WORDS) + " "
        phrase_hits = {
            slug: sum(
                1 for phrase in phrases if phrase and (f" {phrase} " in normalised_query or f" {phrase} " in compact_query)
            )
            for slug, phrases in self._phrases_by_slug.items()
        }
        scored: list[tuple[float, _IndexedPassage]] = []
        for p in self._passages:
            score = 0.0
            for token in query_tokens:
                tf = p.weighted_tf.get(token)
                if not tf:
                    continue
                norm = _BM25_K1 * (1 - _BM25_B + _BM25_B * p.length / self._avg_len)
                score += self._idf[token] * tf * (_BM25_K1 + 1) / (tf + norm)
            score += _PHRASE_BONUS * phrase_hits.get(p.article.slug, 0)
            if score > 0:
                scored.append((score, p))
        scored.sort(key=lambda item: (-item[0], item[1].article.order, item[1].section.anchor))
        return scored

    def retrieve(self, query: str, *, limit: int = 4, max_per_article: int = 2) -> list[RetrievedPassage]:
        """The top passages for a question, best first. Empty when nothing
        matches at all; callers decide confidence with ``is_confident``."""
        scored = self._score_passages(query)
        if not scored:
            return []
        query_tokens = set(tokenize(query))
        best = scored[0][0]
        per_article: Counter[str] = Counter()
        results: list[RetrievedPassage] = []
        for score, p in scored:
            if score < best * _RELATIVE_CUTOFF:
                break
            if per_article[p.article.slug] >= max_per_article:
                continue
            per_article[p.article.slug] += 1
            results.append(
                RetrievedPassage(
                    passage_id=p.section.passage_id,
                    article_slug=p.article.slug,
                    article_title=p.article.title,
                    heading=p.section.heading,
                    text=p.section.text,
                    score=round(score, 3),
                    coverage=round(sum(1 for t in query_tokens if t in p.weighted_tf) / len(query_tokens), 3),
                )
            )
            if len(results) >= limit:
                break
        return results

    def search_articles(self, query: str, *, limit: int = 10) -> list[ArticleHit]:
        """Article-level search for the Help page: each article scored by
        its best passage, so the page and the chat agree on relevance."""
        best: dict[str, float] = {}
        for score, p in self._score_passages(query):
            best.setdefault(p.article.slug, score)
        hits = [ArticleHit(self._by_slug[slug], round(score, 3)) for slug, score in best.items()]
        hits.sort(key=lambda h: (-h.score, h.article.order))
        return hits[:limit]


def is_confident(passages: list[RetrievedPassage]) -> bool:
    """Whether the best passage is a strong enough match to let the
    support lane answer at all. Deliberately permissive at the margin: the
    explain step must still declare the passages sufficient, and its answer
    is then verified against them (app/ai/support_guard.py)."""
    if not passages:
        return False
    top = passages[0]
    return top.score >= MIN_CONFIDENT_SCORE or (top.score >= MIN_FULLY_COVERED_SCORE and top.coverage >= 1.0)


def load_articles(content_dir: Path = CONTENT_DIR) -> list[HelpArticle]:
    return [_load_article(path) for path in sorted(content_dir.glob("*.md"))]


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(load_articles())
