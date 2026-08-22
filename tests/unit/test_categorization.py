"""Unit tests for CategorizationService : category, root cause and conduct flags.

SPEC §5: a deterministic policy maps hard signals to *mandatory* conduct flags that the
model cannot remove : a vulnerable-customer keyword forces a VULNERABLE_CUSTOMER flag,
and a breach of the complaint-handling deadline forces a DEADLINE_RISK flag. The LLM may
add further flags (e.g. regulatory_breach) but never override the deterministic ones.
"""

from __future__ import annotations

from datetime import date

import pytest
from tests.conftest import FakeKnowledgeBase, FakeLLM
from tests.fixtures import sample_complaints

from complaints_review.domain.categorization_service import CategorizationService
from complaints_review.domain.models import (
    Categorization,
    ComplaintCategory,
    ConductFlagKind,
    Severity,
)
from complaints_review.domain.policy import ComplaintPolicy

VALID = sample_complaints.VALID_SOURCE_IDS


def _service() -> CategorizationService:
    return CategorizationService(FakeLLM(), FakeKnowledgeBase())


def test_categorization_is_grounded_and_well_formed():
    service = _service()
    categorization, flags = service.categorize(
        sample_complaints.SAMPLE_COMPLAINT,
        sample_complaints.SAMPLE_COMPLAINT.narrative,
        list(sample_complaints.SAMPLE_PASSAGES),
    )
    assert isinstance(categorization, Categorization)
    assert categorization.category is ComplaintCategory.MIS_SELLING
    assert categorization.root_cause.description
    assert isinstance(categorization.severity, Severity)
    # Citations map to retrieved sources with page provenance.
    assert categorization.citations
    for c in categorization.citations:
        assert c.source_id in VALID
        assert c.page is not None


def test_vulnerability_keyword_forces_deterministic_flag():
    service = _service()
    # SAMPLE_COMPLAINT narrative contains "vulnerable" and "bereaved".
    _categorization, flags = service.categorize(
        sample_complaints.SAMPLE_COMPLAINT,
        sample_complaints.SAMPLE_COMPLAINT.narrative,
        list(sample_complaints.SAMPLE_PASSAGES),
    )
    kinds = {f.kind for f in flags}
    assert ConductFlagKind.VULNERABLE_CUSTOMER in kinds


def test_deadline_breach_forces_deadline_flag():
    service = _service()
    # received 2026-06-01; "now" set well past the 21-day window.
    _categorization, flags = service.categorize(
        sample_complaints.SAMPLE_COMPLAINT,
        sample_complaints.SAMPLE_COMPLAINT.narrative,
        list(sample_complaints.SAMPLE_PASSAGES),
        now=date(2026, 7, 1),
    )
    kinds = {f.kind for f in flags}
    assert ConductFlagKind.DEADLINE_RISK in kinds


def test_deadline_policy_override_changes_boundary():
    service = CategorizationService(
        FakeLLM(), FakeKnowledgeBase(), policy=ComplaintPolicy(deadline_days=45)
    )
    _categorization, flags = service.categorize(
        sample_complaints.SAMPLE_COMPLAINT,
        "ordinary service concern",
        list(sample_complaints.SAMPLE_PASSAGES),
        now=date(2026, 7, 1),
    )
    assert ConductFlagKind.DEADLINE_RISK not in {flag.kind for flag in flags}


def test_no_false_deterministic_flags_on_plain_complaint():
    service = _service()
    # PLAIN_COMPLAINT has no vulnerability signal; "now" within the window.
    _categorization, flags = service.categorize(
        sample_complaints.PLAIN_COMPLAINT,
        sample_complaints.PLAIN_COMPLAINT.narrative,
        list(sample_complaints.SAMPLE_PASSAGES),
        now=date(2026, 6, 20),
    )
    kinds = {f.kind for f in flags}
    assert ConductFlagKind.VULNERABLE_CUSTOMER not in kinds
    assert ConductFlagKind.DEADLINE_RISK not in kinds


def test_llm_flags_are_kept_when_not_already_set():
    service = _service()
    # The FakeLLM proposes a regulatory_breach flag; it must survive the merge.
    _categorization, flags = service.categorize(
        sample_complaints.PLAIN_COMPLAINT,
        sample_complaints.PLAIN_COMPLAINT.narrative,
        list(sample_complaints.SAMPLE_PASSAGES),
        now=date(2026, 6, 20),
    )
    kinds = {f.kind for f in flags}
    assert ConductFlagKind.REGULATORY_BREACH in kinds


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
