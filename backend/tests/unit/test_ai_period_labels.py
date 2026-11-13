"""ORLA-91 eval findings in how a period reaches the explain call:

- _with_period_labels: "what was my revenue last month?" was answered with
  revenue.previous (the comparison period) and periods were UTC timestamps,
  so the explain context now carries business-local date labels and names
  the comparison figure for what it is.
- _resolve_dates: the default trailing window ignored answer_question's
  `now` (resolved against the wall clock inside each calc function).
"""

from datetime import date, datetime, timezone

from app.ai.service import ClassifyResult, _resolve_dates, _with_period_labels
from app.models.business import Business

FINANCIAL = {
    "period": {"start": "2026-09-30T23:00:00Z", "end": "2026-11-01T00:00:00Z"},
    "previous_period": {"start": "2026-08-30T22:00:00Z", "end": "2026-09-30T23:00:00Z"},
    "revenue": {"current": "34166.77", "previous": "35471.83", "change_pct": "-3.7"},
    "gross_margin": {"gross_margin_pct": "45.6"},
}


def test_periods_become_local_date_labels():
    labelled = _with_period_labels(FINANCIAL, "Europe/Dublin")
    assert labelled["period_asked_about"] == "Thu 1 Oct 2026 to Sat 31 Oct 2026 (2026-10-01 to 2026-10-31)"
    assert "period" not in labelled and "previous_period" not in labelled
    assert list(labelled)[0] == "period_asked_about"


def test_previous_revenue_is_named_as_the_comparison_period():
    revenue = _with_period_labels(FINANCIAL, "Europe/Dublin")["revenue"]
    assert revenue == {
        "current": "34166.77",
        # 30 Aug 22:00 UTC is 23:00 Dublin — an hour off midnight from the
        # UTC span arithmetic across the clock change, labelled as 31 Aug.
        "comparison_period": "Mon 31 Aug 2026 to Wed 30 Sep 2026 (2026-08-31 to 2026-09-30)",
        "comparison_period_revenue": "35471.83",
        "change_pct_vs_comparison_period": "-3.7",
        "change_amount_vs_comparison_period": "-1305.06",
    }


def test_comparison_period_derived_when_context_has_none():
    workshop = {
        "period": {"start": "2026-10-14T23:00:00Z", "end": "2026-11-14T00:00:00Z"},
        "revenue": {"current": "1939.00", "previous": "2222.00", "change_pct": "-12.7"},
    }
    revenue = _with_period_labels(workshop, "Europe/Dublin")["revenue"]
    assert revenue["comparison_period"] == "Tue 15 Sep 2026 to Wed 14 Oct 2026 (2026-09-15 to 2026-10-14)"
    assert revenue["comparison_period_revenue"] == "2222.00"


def test_context_without_a_period_is_unchanged():
    forecast = {"horizon_days": 7, "revenue": {"result": {"total_point": "1"}}}
    assert _with_period_labels(forecast, "Europe/Dublin") is forecast


def test_default_recent_window_is_anchored_on_now():
    business = Business(name="B", template="bicycle_shop", timezone="Europe/Dublin")
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    start, end = _resolve_dates(business, ClassifyResult(intent="financial_performance"), now)
    assert (start, end) == (date(2026, 10, 15), date(2026, 11, 13))


def test_default_recent_uses_the_business_local_day():
    business = Business(name="B", template="bicycle_shop", timezone="Pacific/Auckland")
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)  # already 14 Nov in Auckland
    _start, end = _resolve_dates(business, ClassifyResult(intent="financial_performance"), now)
    assert end == date(2026, 11, 14)


def test_comparison_dropped_when_not_asked_for():
    labelled = _with_period_labels(FINANCIAL, "Europe/Dublin", include_comparison=False)
    assert labelled["revenue"] == {"current": "34166.77"}


def test_comparison_wording_is_detected():
    from app.ai.service import _asks_for_comparison

    for question in (
        "Is revenue up or down compared with the previous period?",
        "What did I make last month compared with the month before?",
        "How is the workshop doing?",
        "And the month before?",
        "What was it in the previous period?",
        "Did sales grow?",
    ):
        assert _asks_for_comparison(question), question
    for question in ("What was my revenue last month?", "How much did I sell last week in euros?", "Revenue yesterday?"):
        assert not _asks_for_comparison(question), question
