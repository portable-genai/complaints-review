"""Unit tests for ComplaintReviewService : the SPEC §5 review pipeline.

Pipeline (SPEC §5, full R1 safety because the file carries customer PII):
    redact(narrative) -> guardrail.screen(INPUT)
      -> [if blocked: audit BLOCKED + raise]
      -> extract documents (+ redact each) -> A2 retrieve policy/regulatory guidance
      -> llm summarise -> categorise (deterministic + LLM flags) -> llm draft response
      -> assemble ComplaintReview -> guardrail.screen(OUTPUT) -> review (always) -> audit

These tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

import pytest
from tests.conftest import BlockingGuardrail, load_service
from tests.fixtures import sample_complaints

from complaints_review.domain.errors import GuardrailBlockedError, RetrievalEmptyError
from complaints_review.domain.models import (
    ComplaintReview,
    Decision,
    Direction,
)

ACTOR = "conduct-officer@bank.test"


# --------------------------------------------------------------------------- #
# Redaction happens BEFORE retrieval (P-04 / R1: minimise PII to model & store).
# --------------------------------------------------------------------------- #
def test_redaction_runs_before_retrieval(review_service, redaction, knowledge_base):
    review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)

    # Redaction was invoked on the *raw* narrative (which carried the NRIC).
    assert redaction.calls, "redaction.redact was never called"
    assert any("S1234567A" in call for call in redaction.calls)

    # Retrieval ran, and the query text it saw must already be de-identified: the raw
    # NRIC / email must never reach the governed RAG backend.
    assert knowledge_base.calls, "knowledge_base.search was never called"
    query_text = knowledge_base.calls[0].text
    assert "S1234567A" not in query_text
    assert "jane.doe@example.com" not in query_text


# --------------------------------------------------------------------------- #
# Blocked input: raises + audit BLOCKED + no LLM / retrieval.
# --------------------------------------------------------------------------- #
def test_blocked_input_raises_and_audits(extraction, knowledge_base, llm, redaction, tracer, audit):
    blocking = BlockingGuardrail(block_input=True)
    service = load_service("ComplaintReviewService")(
        extraction, knowledge_base, llm, blocking, redaction, tracer, audit
    )

    with pytest.raises(GuardrailBlockedError):
        service.review(sample_complaints.MALICIOUS_COMPLAINT, actor=ACTOR)

    # The LLM and retrieval must never run once the input is blocked.
    assert llm.requests == []
    assert knowledge_base.calls == []

    # Exactly one BLOCKED audit event was written, already redacted.
    blocked = [e for e in audit.events if e.decision is Decision.BLOCKED]
    assert blocked, "expected an audit event with decision=BLOCKED"
    assert blocked[0].actor == ACTOR
    assert blocked[0].action == "review"


def test_blocked_input_screens_input_direction_only(
    extraction, knowledge_base, llm, redaction, tracer, audit
):
    blocking = BlockingGuardrail(block_input=True)
    service = load_service("ComplaintReviewService")(
        extraction, knowledge_base, llm, blocking, redaction, tracer, audit
    )
    with pytest.raises(GuardrailBlockedError):
        service.review(sample_complaints.MALICIOUS_COMPLAINT, actor=ACTOR)

    directions = [d for _, d in blocking.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT not in directions


# --------------------------------------------------------------------------- #
# Normal path: well-formed review, cited with pages, human-reviewed, audited.
# --------------------------------------------------------------------------- #
def test_normal_path_review_is_well_formed(review_service):
    review = review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)

    assert isinstance(review, ComplaintReview)
    assert review.file_id == sample_complaints.SAMPLE_COMPLAINT.id
    assert review.requires_human_review is True

    # Summary, categorisation and a draft response are all present.
    assert review.summary.issue
    assert review.categorization.root_cause.description
    assert review.draft_response is not None

    # Citations carry page-level provenance and map to retrieved sources.
    valid = sample_complaints.VALID_SOURCE_IDS
    for c in review.summary.citations:
        assert c.source_id in valid
        assert c.page is not None


def test_draft_response_is_always_a_draft_never_sent(review_service):
    review = review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    draft = review.draft_response
    assert draft is not None
    assert draft.is_draft is True
    assert draft.requires_human_review is True
    assert "DRAFT" in draft.body  # the never-sent marker is stamped on every draft


def test_normal_path_audit_record_is_redacted(review_service, audit):
    review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    assert audit.events
    for event in audit.events:
        assert "S1234567A" not in event.redacted_prompt
        assert "jane.doe@example.com" not in event.redacted_prompt


def test_normal_path_audits_as_escalated(review_service, audit):
    # A complaint review is consequential : audited as ESCALATED (human checker, P-06).
    review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    review_events = [e for e in audit.events if e.action == "review"]
    assert review_events
    assert review_events[-1].decision is Decision.ESCALATED


def test_normal_path_wrapped_in_tracer_span(review_service, tracer):
    review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    assert "complaint.review" in tracer.spans


def test_output_guardrail_screens_draft(review_service, guardrail):
    review_service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    directions = [d for _, d in guardrail.calls]
    assert Direction.INPUT in directions
    assert Direction.OUTPUT in directions


# --------------------------------------------------------------------------- #
# Empty corpus is a hard error : never an ungrounded conduct decision.
# --------------------------------------------------------------------------- #
def test_empty_corpus_raises(
    extraction, empty_knowledge_base, llm, guardrail, redaction, tracer, audit
):
    service = load_service("ComplaintReviewService")(
        extraction, empty_knowledge_base, llm, guardrail, redaction, tracer, audit
    )
    with pytest.raises(RetrievalEmptyError):
        service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)


# --------------------------------------------------------------------------- #
# Sub-artifact entry points (summary / draft) are R1-safe and audited too.
# --------------------------------------------------------------------------- #
def test_summarize_only(review_service, audit):
    summary = review_service.summarize(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    assert summary.issue
    assert any(e.action == "summary" for e in audit.events)


def test_draft_response_only(review_service, audit):
    draft = review_service.draft_response(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    assert draft.is_draft is True
    assert draft.requires_human_review is True
    assert any(e.action == "draft_response" for e in audit.events)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
