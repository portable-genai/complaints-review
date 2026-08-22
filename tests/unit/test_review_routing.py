"""Unit tests for rule R8: an escalated complaint review is routed to Hrz7, not left as a boolean.

These prove the producer half of R8 without a live console, using the ``local`` in-memory outbox
adapter and the shared payload builder:

* the review pipeline enqueues exactly ONE review, carrying the maker (actor), tenant, case_ref
  (file id) and a ``complaint_review:*`` action;
* the payload REDACTS the subject, summary and citation snippets before the wire (defense in depth,
  even though the pipeline already ran redaction), and maps severity + dual control from the
  review's category/severity/conduct flags;
* the router is OPTIONAL: a service built without one still assembles and audits the review, it
  simply is not forwarded to a console.

All data here is fictional.
"""

from __future__ import annotations

from tests.conftest import load_service
from tests.fixtures import sample_complaints

from complaints_review.adapters._review_payload import review_to_review
from complaints_review.adapters.local.review_router import LocalReviewRouter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.models import (
    Categorization,
    Channel,
    Citation,
    ComplaintCategory,
    ComplaintReview,
    ComplaintSummary,
    ConductFlag,
    ConductFlagKind,
    RootCause,
    Severity,
    SourceType,
)

ACTOR = "conduct-officer@bank.test"
TENANT = "demo-bank"

_SETTINGS = Settings(
    profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:")
)


def _router() -> LocalReviewRouter:
    return LocalReviewRouter(_SETTINGS)


def _review(
    *,
    severity: Severity = Severity.LOW,
    conduct_flags: tuple[ConductFlag, ...] = (),
    snippet: str = "the customer said nothing sensitive",
) -> ComplaintReview:
    """A minimal, fictional ComplaintReview for payload assertions."""
    citation = Citation(
        source_id="complaints-handling-policy",
        source_type=SourceType.POLICY,
        title="Complaint handling policy",
        page=3,
        snippet=snippet,
    )
    return ComplaintReview(
        file_id="CMP-FAKE-9001",
        summary=ComplaintSummary(
            issue="fee dispute on a savings account",
            products=("savings account",),
            channel=Channel.APP,
            citations=(citation,),
        ),
        categorization=Categorization(
            category=ComplaintCategory.FEES_CHARGES,
            root_cause=RootCause(description="fee applied in error", systemic=False),
            severity=severity,
            citations=(citation,),
        ),
        conduct_flags=conduct_flags,
    )


# --------------------------------------------------------------------------- #
# The pipeline routes the escalation exactly once, with the right envelope.
# --------------------------------------------------------------------------- #
def test_review_enqueues_exactly_one_review(
    extraction, knowledge_base, llm, guardrail, redaction, tracer, audit
):
    router = _router()
    service = load_service("ComplaintReviewService")(
        extraction, knowledge_base, llm, guardrail, redaction, tracer, audit, None, router
    )

    service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR, tenant=TENANT)

    pending = router.outbox.pending()
    assert len(pending) == 1, "an escalated review must be routed to Hrz7 exactly once"
    entry = pending[0]
    review = entry.review
    assert review.maker == ACTOR
    assert review.tenant == TENANT
    assert review.case_ref == sample_complaints.SAMPLE_COMPLAINT.id
    assert review.action.startswith("complaint_review:")
    assert review.required_approvals >= 1


def test_optional_router_service_still_works(
    extraction, knowledge_base, llm, guardrail, redaction, tracer, audit
):
    """A service built WITHOUT a router still assembles + audits the review (no crash)."""
    service = load_service("ComplaintReviewService")(
        extraction, knowledge_base, llm, guardrail, redaction, tracer, audit
    )
    review = service.review(sample_complaints.SAMPLE_COMPLAINT, actor=ACTOR)
    assert review.requires_human_review is True


# --------------------------------------------------------------------------- #
# Redaction before the wire (defense in depth) + severity / dual-control mapping.
# --------------------------------------------------------------------------- #
def test_payload_redacts_subject_and_citation_snippets():
    # Fictional PII planted in a citation snippet + the summary issue path.
    review = _review(
        snippet="contact the customer at jane.doe@example.com; NRIC S1234567A on file",
    )
    payload = review_to_review(review, maker=ACTOR, tenant=TENANT)

    wire = payload.subject + " " + payload.summary
    wire += " " + " ".join(c.snippet for c in payload.citations)
    assert "jane.doe@example.com" not in wire, "email must be redacted before the wire"
    assert "S1234567A" not in wire, "NRIC must be redacted before the wire"
    # And the citation snippet specifically is scrubbed.
    assert payload.citations
    assert all("@example.com" not in c.snippet for c in payload.citations)


def test_low_severity_no_flags_is_single_control():
    payload = review_to_review(_review(severity=Severity.LOW), maker=ACTOR, tenant=TENANT)
    assert payload.severity == Severity.LOW.value
    assert payload.required_approvals == 1


def test_high_severity_requires_dual_control():
    payload = review_to_review(_review(severity=Severity.HIGH), maker=ACTOR, tenant=TENANT)
    assert payload.severity == Severity.HIGH.value
    assert payload.required_approvals == 2


def test_senior_escalating_conduct_flag_requires_dual_control():
    flag = ConductFlag(
        kind=ConductFlagKind.VULNERABLE_CUSTOMER,
        severity=Severity.MEDIUM,
        detail="recently bereaved customer",
    )
    payload = review_to_review(
        _review(severity=Severity.MEDIUM, conduct_flags=(flag,)), maker=ACTOR, tenant=TENANT
    )
    # A vulnerable-customer flag escalates to a senior checker -> four eyes, even at MEDIUM.
    assert payload.required_approvals == 2
    assert payload.sod_group == "complaints-maker-checker"
