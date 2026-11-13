"""The help knowledge base (PR-5.7, E26): content integrity, feature
coverage, and the deterministic retriever the support lane and the Help
page both rely on."""

import pytest

from app.support.knowledge_base import (
    HelpContentError,
    KnowledgeBase,
    get_knowledge_base,
    is_confident,
    load_articles,
    tokenize,
)
from app.templates import list_templates

# One article per current feature area (the E26 "covers every feature that
# exists today" bar). Adding a feature without help content should fail
# review; removing an article fails this test.
EXPECTED_ARTICLES = {
    "getting-started",
    "sign-up-and-log-in",
    "business-types",
    "free-pilot-access",
    "uploading-your-data",
    "upload-sales",
    "upload-stock-count",
    "upload-purchases",
    "upload-repairs",
    "column-mapping",
    "undo-and-reimport",
    "supplier-invoice-pdf",
    "dashboard-overview",
    "metrics-explained",
    "findings-and-alerts",
    "forecast",
    "reports",
    "reorder-rules",
    "suppliers",
    "transactions",
    "notifications",
    "branches",
    "staff-and-invites",
    "billing",
    "account-and-profile",
    "ask-orla",
    "contact-support",
}
CATEGORIES = {
    "Getting started",
    "Uploading data",
    "Dashboard and insights",
    "Reports",
    "Stock and suppliers",
    "Team, branches and billing",
    "Account and help",
}


@pytest.fixture(scope="module")
def kb() -> KnowledgeBase:
    return get_knowledge_base()


def test_every_current_feature_has_an_article(kb):
    assert {a.slug for a in kb.articles} == EXPECTED_ARTICLES


def test_articles_are_well_formed(kb):
    for article in kb.articles:
        assert article.category in CATEGORIES, article.slug
        assert article.title and article.summary and article.keywords, article.slug
        assert article.version >= 1
        assert len(article.updated) == 10  # ISO date
        assert article.sections, article.slug
        assert len({s.anchor for s in article.sections}) == len(article.sections), f"duplicate heading in {article.slug}"
        assert "http://" not in article.body and "https://" not in article.body, "help content links stay in-app"


def test_business_types_article_lists_every_registered_type(kb):
    body = kb.get("business-types").body
    templates = list_templates()
    assert len(templates) == 19
    for template in templates:
        assert template.label in body, template.label


def test_prices_in_help_match_the_decision_register(kb):
    billing = kb.get("billing").body
    # BD-005 (€80), BD-007 (€30 branch), €5 employee seat.
    assert "€80 a month" in billing and "€30 a month" in billing and "€5 a month" in billing


@pytest.mark.parametrize(
    ("question", "expected_slug"),
    [
        ("How do I upload my stock count?", "upload-stock-count"),
        ("how do I undo an import", "undo-and-reimport"),
        ("Why did my report disappear?", "reports"),
        ("can I download the report as a PDF?", "reports"),
        ("how do I add a staff member", "staff-and-invites"),
        ("how much does ORLA cost", "billing"),
        ("how do I add another location", "branches"),
        ("where do I set reorder points", "reorder-rules"),
        ("what is the pilot", "free-pilot-access"),
        ("my invoice PDF says it's scanned", "supplier-invoice-pdf"),
        ("what does remap do", "column-mapping"),
        ("how do I talk to a human", "contact-support"),
        ("how do I change my business type", "business-types"),
        ("how do i log in with google", "sign-up-and-log-in"),
    ],
)
def test_how_to_questions_retrieve_the_right_article_confidently(kb, question, expected_slug):
    passages = kb.retrieve(question)
    assert is_confident(passages), (question, passages[:1])
    assert passages[0].article_slug == expected_slug


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital of France?",
        "does orla integrate with lightspeed",
        "how do I connect to Shopify",
        "how do I print a barcode label",
        "",
    ],
)
def test_off_topic_questions_are_not_confident(kb, question):
    assert not is_confident(kb.retrieve(question))


def test_retrieval_is_deterministic_and_bounded(kb):
    first = kb.retrieve("how do I upload my sales file", limit=4)
    second = kb.retrieve("how do I upload my sales file", limit=4)
    assert first == second
    assert 0 < len(first) <= 4
    per_article = {}
    for p in first:
        per_article[p.article_slug] = per_article.get(p.article_slug, 0) + 1
    assert max(per_article.values()) <= 2
    assert all(first[i].score >= first[i + 1].score for i in range(len(first) - 1))


def test_passage_lookup_round_trips(kb):
    passage = kb.retrieve("how do I upload my stock count")[0]
    section = kb.passage(passage.passage_id)
    assert section is not None and section.text == passage.text
    assert kb.passage("no-such-article#x") is None


def test_article_search_ranks_whole_articles(kb):
    hits = kb.search_articles("invite link")
    assert hits[0].article.slug == "staff-and-invites"
    assert len({h.article.slug for h in hits}) == len(hits)
    assert kb.search_articles("zzzz qqqq") == []


def test_tokenizer_stems_and_expands_synonyms():
    assert tokenize("Uploading uploaded uploads") == ["upload", "upload", "upload"]
    assert tokenize("invoices") == tokenize("invoice")
    assert tokenize("purchases") == tokenize("purchase")
    assert "stock" in tokenize("stocktake") and "count" in tokenize("stocktake")
    assert tokenize("how do I do it") == []


def test_malformed_article_fails_loudly(tmp_path):
    (tmp_path / "bad.md").write_text("no front matter here\n## Section\ntext", encoding="utf-8")
    with pytest.raises(HelpContentError):
        load_articles(tmp_path)


def test_article_slug_must_match_file_name(tmp_path):
    (tmp_path / "one.md").write_text(
        "---\nslug: two\ntitle: T\ncategory: Reports\nsummary: S\nversion: 1\nupdated: 2026-11-13\n---\n## A\nb\n",
        encoding="utf-8",
    )
    with pytest.raises(HelpContentError):
        load_articles(tmp_path)
