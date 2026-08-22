"""Built-in synthetic policy / regulatory corpus for the ``local`` profile.

A tiny, clearly-fictional set of complaint-handling policy and MAS fair-dealing
passages (with page-level citations) so the local knowledge-base adapter has something
to ground a complaint review on out of the box, and the end-to-end CLI smoke run returns
a real cited artifact with no external corpus. The text is invented; the source ids /
titles are plausible but fictional and must not be treated as the real instruments.

This mirrors ``tests/fixtures/sample_complaints`` so the local adapters and the
unit-test fixtures share one deterministic corpus, but it lives under ``src`` (not
``tests``) so the shipped package can seed itself without importing the test tree. The
source ids match the ones the offline eval gate (``eval/run_eval.py``) cites.
"""

from __future__ import annotations

from ...domain.models import Citation, RetrievedPassage, SourceType

POLICY_SOURCE_ID = "complaints-handling-policy"
REG_SOURCE_ID = "mas-fair-dealing-guidelines"


def _passage(
    *,
    source_id: str,
    source_type: SourceType,
    title: str,
    page: int,
    text: str,
    snippet: str,
    score: float,
) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        citation=Citation(
            source_id=source_id,
            source_type=source_type,
            title=title,
            url=f"https://example.test/{source_id}",
            page=page,
            snippet=snippet,
            score=score,
        ),
        score=score,
    )


# A small, deterministic corpus. Page numbers are required for conduct provenance.
SEED_PASSAGES: tuple[RetrievedPassage, ...] = (
    _passage(
        source_id=POLICY_SOURCE_ID,
        source_type=SourceType.POLICY,
        title="Group Complaints Handling Policy",
        page=3,
        text=(
            "A complaint must receive an acknowledgement promptly and a final response "
            "within the complaint-handling window; vulnerable customers must be handled "
            "with additional care and remediation considered where harm occurred."
        ),
        snippet="final response within the complaint-handling window",
        score=0.93,
    ),
    _passage(
        source_id=REG_SOURCE_ID,
        source_type=SourceType.REGULATION,
        title="MAS Guidelines on Fair Dealing",
        page=12,
        text=(
            "Financial institutions should deal fairly with customers, ensure products "
            "are suitable, and remediate where a product was mis-sold or fees were "
            "applied without a proper basis."
        ),
        snippet="deal fairly with customers",
        score=0.88,
    ),
)
