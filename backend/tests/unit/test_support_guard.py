"""Grounding/refusal checks for support answers (PR-5.7): a how-to answer
reaches the user only if it is built from the help passages it cites."""

import json

from app.ai.support_guard import SupportModelOutput, parse_support_output, verify_support_answer

PASSAGES = {
    "upload-stock-count#how-to-upload-a-stock-count": (
        "1. Export your current stock list or stock-take from your till, POS or spreadsheet.\n"
        '2. Open Upload data and choose "Inventory / stock count" under "What does this file contain?".\n'
        '3. Select your file and select "Upload".\n'
        '4. Check the column matches under "Confirm what each column means" and select "Confirm mapping".\n'
        '5. Under "Past uploads", select "Run import".'
    ),
    "reports#why-a-report-disappeared-7-day-availability": (
        "Each report stays available for 7 days after it is generated; the \"Available until\" date shows exactly "
        "when. After that it is removed from the list."
    ),
}
QUESTION = "How do I upload my stock count?"


def _output(answer, ids=("upload-stock-count#how-to-upload-a-stock-count",), answerable=True):
    return SupportModelOutput(answerable=answerable, answer=answer, passage_ids=tuple(ids))


def test_faithful_answer_passes():
    answer = (
        'Export your current stock list from your till or POS. Then open Upload data, choose "Inventory / stock '
        'count", select your file and select "Upload". Check the column matches, select "Confirm mapping", and '
        'finally select "Run import" under "Past uploads".'
    )
    result = verify_support_answer(_output(answer), passages_by_id=PASSAGES, question=QUESTION)
    assert result.grounded, result.reasons


def test_numbered_steps_are_not_treated_as_numeric_claims():
    answer = '1. Open Upload data. 2. Choose "Inventory / stock count". 3. Select "Upload", then "Run import".'
    result = verify_support_answer(_output(answer), passages_by_id=PASSAGES, question=QUESTION)
    assert result.grounded, result.reasons


def test_invented_button_is_rejected():
    answer = 'Go to Settings, open "Integrations" and select "Sync stock now".'
    result = verify_support_answer(_output(answer), passages_by_id=PASSAGES, question=QUESTION)
    assert not result.grounded
    assert any(r.startswith("unsupported_label") for r in result.reasons)


def test_invented_steps_without_quotes_are_rejected_by_word_support():
    answer = (
        "Connect your Shopify store under Settings, enable automatic synchronisation, and your inventory levels "
        "will refresh every night via the integration marketplace."
    )
    result = verify_support_answer(_output(answer), passages_by_id=PASSAGES, question=QUESTION)
    assert not result.grounded
    assert any(r.startswith("low_support") for r in result.reasons)


def test_invented_number_is_rejected():
    answer = "Reports stay available for 30 days after they are generated."
    output = _output(answer, ids=("reports#why-a-report-disappeared-7-day-availability",))
    result = verify_support_answer(output, passages_by_id=PASSAGES, question="why did my report disappear")
    assert not result.grounded
    assert "unsupported_number:30" in result.reasons


def test_number_from_the_passage_is_allowed():
    answer = 'Each report stays available for 7 days after it is generated — check the "Available until" date.'
    output = _output(answer, ids=("reports#why-a-report-disappeared-7-day-availability",))
    result = verify_support_answer(output, passages_by_id=PASSAGES, question="why did my report disappear")
    assert result.grounded, result.reasons


def test_unknown_or_missing_citation_is_rejected():
    answer = 'Open Upload data and select "Upload".'
    assert not verify_support_answer(_output(answer, ids=()), passages_by_id=PASSAGES, question=QUESTION).grounded
    result = verify_support_answer(_output(answer, ids=("made-up#section",)), passages_by_id=PASSAGES, question=QUESTION)
    assert not result.grounded


def test_links_are_rejected():
    answer = 'Open Upload data and select "Upload" — see https://example.com/help.'
    result = verify_support_answer(_output(answer), passages_by_id=PASSAGES, question=QUESTION)
    assert "contains_link" in result.reasons


def test_model_declining_is_a_refusal():
    result = verify_support_answer(_output("", ids=(), answerable=False), passages_by_id=PASSAGES, question=QUESTION)
    assert not result.grounded
    assert result.reasons == ["model_declared_unanswerable"]


def test_parse_support_output_accepts_only_the_exact_shape():
    good = json.dumps({"answerable": True, "answer": " Hi ", "passage_ids": ["a#b"]})
    parsed = parse_support_output(good)
    assert parsed == SupportModelOutput(answerable=True, answer="Hi", passage_ids=("a#b",))
    fenced = "```json\n" + good + "\n```"
    assert parse_support_output(fenced) == parsed
    assert parse_support_output(None) is None
    assert parse_support_output("Sure! Open Upload data.") is None
    assert parse_support_output(json.dumps({"answerable": "yes", "answer": "x", "passage_ids": []})) is None
    assert parse_support_output(json.dumps({"answerable": True, "answer": "x", "passage_ids": "a#b"})) is None
    assert parse_support_output(json.dumps(["not", "an", "object"])) is None
