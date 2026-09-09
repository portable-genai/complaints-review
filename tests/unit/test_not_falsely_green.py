"""Prove every eval metric can go RED: a degraded case must score below its threshold.

This repository shipped four gated metrics and no falsification proof at all, which is the
one gap that makes every other green result unreadable. A metric that cannot fail proves
nothing, and nothing here had ever been shown able to fail: the gate had only ever been
observed passing, which is exactly what a broken scorer also looks like.

Each scorer in ``eval/run_eval.py`` is imported rather than re-implemented, and fed the same
reviewed complaint twice: once as the pipeline produced it, and once carrying precisely the
defect that metric exists to catch. Re-implementing the scorer here would prove that a local
copy works while the gate stayed blind, which the fleet already recorded as a lesson.

The four defects, one per metric:

* **categorisation_accuracy** : the reviewer's expected category is changed, so the pipeline's
  answer is now the wrong one. The metric compares against the DATASET'S label, so degrading
  the label is the honest inversion of degrading the answer.
* **groundedness** : the citations are stripped off the categorisation, which is the shape of
  a model that asserted a category with nothing behind it.
* **citation_accuracy** : a citation is redirected at a source id the knowledge base does not
  contain, which a presence check could never catch.
* **pii_safety** : a raw market identifier is re-introduced into the audited
  ``redacted_prompt`` AFTER redaction ran, which is the leak the metric exists for.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    _PII_BY_JURISDICTION,
    DEFAULT_DATASET,
    THRESHOLDS,
    FakeAuditSink,
    GoldenExample,
    _build_adapters,
    _make_service,
    _planted_narrative,
    _to_file,
    load_golden,
    score_categorisation,
    score_citation_accuracy,
    score_groundedness,
    score_pii_safety,
)

from complaints_review.domain.models import Citation, ComplaintReview, SourceType

_GOLDEN = load_golden(DEFAULT_DATASET)
#: A case that plants a market identifier, so pii_safety has a target it could miss.
_WITH_PII = next(case for case in _GOLDEN if case.pii_jurisdiction)
#: A case the reviewer expects to cite something, so citation_accuracy is not vacuous.
_WITH_CITATIONS = next(case for case in _GOLDEN if case.must_cite_source_ids)


def _reviewed(example: GoldenExample) -> tuple[ComplaintReview, list[object]]:
    """Run one golden case through the REAL review service, as the gate does."""
    adapters = _build_adapters(_GOLDEN)
    audit = FakeAuditSink()
    service = _make_service(adapters, audit)
    review = service.review(_to_file(example, _planted_narrative(example)), actor="eval-bot")
    return review, list(audit.events)


@pytest.fixture(scope="module")
def cited() -> ComplaintReview:
    review, _ = _reviewed(_WITH_CITATIONS)
    assert review.categorization.citations, (
        "the proof needs a case the pipeline actually cited; without one every citation "
        "metric below would be scoring an empty set"
    )
    return review


def test_categorisation_accuracy_can_go_red(cited: ComplaintReview) -> None:
    wrong = next(
        value
        for value in ("mis-selling", "service-failure", "fees-and-charges", "fraud")
        if value != _WITH_CITATIONS.expected_category
    )
    assert_can_go_red(
        lambda example: score_categorisation(cited, example),
        green=_WITH_CITATIONS,
        red=replace(_WITH_CITATIONS, expected_category=wrong),
        threshold=THRESHOLDS["categorisation_accuracy"],
        metric="categorisation_accuracy",
    )


def test_groundedness_can_go_red(cited: ComplaintReview) -> None:
    uncited = replace(cited, categorization=replace(cited.categorization, citations=()))
    assert_can_go_red(
        score_groundedness,
        green=cited,
        red=uncited,  # a category asserted with nothing behind it
        threshold=THRESHOLDS["groundedness"],
        metric="groundedness",
    )


def test_citation_accuracy_can_go_red(cited: ComplaintReview) -> None:
    invented = Citation(
        source_id="KB-DOES-NOT-EXIST",
        source_type=SourceType.POLICY,
        title="A policy this bank has never published",
        snippet="Cited, plausible, and not in the knowledge base.",
    )
    misdirected = replace(
        cited, categorization=replace(cited.categorization, citations=(invented,))
    )
    assert_can_go_red(
        lambda review: score_citation_accuracy(review, _WITH_CITATIONS),
        green=cited,
        red=misdirected,  # a REAL-looking citation pointing at nothing
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_pii_safety_can_go_red() -> None:
    """The red case re-introduces the raw identifier into the audit trail AFTER redaction."""
    review, events = _reviewed(_WITH_PII)
    assert events, "the proof needs an audited record; pii_safety scans the audit trail"
    identifier = _PII_BY_JURISDICTION[_WITH_PII.pii_jurisdiction]
    leaked = copy.copy(events[0])
    object.__setattr__(
        leaked,
        "redacted_prompt",
        f"{getattr(leaked, 'redacted_prompt', '') or ''} customer identifier {identifier}",
    )
    assert_can_go_red(
        lambda audit_events: score_pii_safety(review, _WITH_PII, audit_events),
        green=events,
        red=[leaked, *events[1:]],
        threshold=THRESHOLDS["pii_safety"],
        metric="pii_safety",
    )
