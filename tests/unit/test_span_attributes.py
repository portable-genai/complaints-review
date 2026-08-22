"""The complaint-review spans carry structural attributes only, never content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit
store. The conftest ``RecordingTracer`` records only span NAMES, so it can never see a
leak: the attributes are thrown away before anything could inspect them. This module keeps
its own recorder that captures ``(name, dict(attributes))`` and asserts two halves:

* the attribute KEY SET is a fixed allowlist (an attribute added "to explain" a review is a
  defect, not an enrichment), and
* no attribute VALUE carries the planted PII from ``SAMPLE_COMPLAINT``'s narrative (NRIC +
  email), the input that would actually leak if any attribute were content-shaped.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from tests.conftest import load_service
from tests.fixtures import sample_complaints

#: The one attribute set every complaint span may carry: enough for "whose call, doing
#: what, how long", and nothing more. Grow this list only for structural, low-cardinality
#: identifiers; never for complaint ids, narratives, summaries or draft text.
ALLOWED_SPAN_ATTRIBUTES = {"action", "actor"}

_ACTOR = "conduct-officer@bank.test"
#: The PII planted in the sample complaint's narrative; a content attribute would carry it.
_PLANTED = ("S1234567A", "jane.doe@example.com")


class _RecordingTracer:
    """Captures every span name AND its attributes so the test can inspect what left."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _service(
    extraction: Any, knowledge_base: Any, llm: Any, guardrail: Any, redaction: Any, audit: Any
) -> tuple[Any, _RecordingTracer]:
    tracer = _RecordingTracer()
    cls = load_service("ComplaintReviewService")
    return cls(extraction, knowledge_base, llm, guardrail, redaction, tracer, audit), tracer


def test_review_opens_exactly_one_named_span(
    extraction, knowledge_base, llm, guardrail, redaction, audit
) -> None:
    service, tracer = _service(extraction, knowledge_base, llm, guardrail, redaction, audit)
    service.review(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    assert [name for name, _ in tracer.spans] == ["complaint.review"]


def test_summary_and_draft_open_their_own_named_spans(
    extraction, knowledge_base, llm, guardrail, redaction, audit
) -> None:
    service, tracer = _service(extraction, knowledge_base, llm, guardrail, redaction, audit)
    service.summarize(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    service.draft_response(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    assert [name for name, _ in tracer.spans] == [
        "complaint.summary",
        "complaint.draft_response",
    ]


def test_every_span_attribute_set_is_the_fixed_allowlist(
    extraction, knowledge_base, llm, guardrail, redaction, audit
) -> None:
    """Whatever the surface and whatever the verdict, no span attaches findings."""
    service, tracer = _service(extraction, knowledge_base, llm, guardrail, redaction, audit)
    service.review(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    service.review(sample_complaints.PLAIN_COMPLAINT, actor=_ACTOR)
    service.summarize(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    service.draft_response(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    assert tracer.spans
    for name, attributes in tracer.spans:
        assert set(attributes) == ALLOWED_SPAN_ATTRIBUTES, name


def test_no_span_attribute_carries_planted_pii(
    extraction, knowledge_base, llm, guardrail, redaction, audit
) -> None:
    """SAMPLE_COMPLAINT's narrative embeds the planted NRIC + email, so a leak would show."""
    service, tracer = _service(extraction, knowledge_base, llm, guardrail, redaction, audit)
    service.review(sample_complaints.SAMPLE_COMPLAINT, actor=_ACTOR)
    emitted = " ".join(
        str(value) for _, attributes in tracer.spans for value in attributes.values()
    )
    for planted in _PLANTED:
        assert planted not in emitted
        assert planted.lower() not in emitted.lower()
