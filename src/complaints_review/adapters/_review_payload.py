"""Shared conversion from an escalated complaint review to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. Redacts the subject
descriptor, summary and citation snippets before they leave the process (R1 / P-04 boundary), using
the shared ``pii-kit`` (the same pack the redaction adapter uses), so no raw customer identifier
reaches human-review-console over the wire; human-review-console redacts again before its own audit
write (defense in depth). The maker (the reviewer/assistant that originated the review) and the
tenant are asserted here and trusted by human-review-console because this is an authenticated S2S
caller (per-hop OBO is the deferred next layer).
"""

from __future__ import annotations

import re

from pii_kit import NATIONAL_ID_PATTERNS, UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit import redact as pii_redact
from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import Citation, ComplaintReview, ConductFlagKind, Severity

# Cap the citations carried on the wire: enough to let a reviewer trace the review without copying
# the entire evidence set into the review console.
_MAX_CITATIONS = 8

# The review console is a shared sink: a review for an SG customer may still quote an HK id, so the
# payload is scrubbed against every jurisdiction's national ids plus universal email/phone,
# regardless of which market configured this producer.
_ALL_PATTERNS = (
    *national_patterns_for(tuple(NATIONAL_ID_PATTERNS.keys())),
    *UNIVERSAL_PATTERNS,
)

# Ordered weakest -> strongest so ``max`` picks the review's most severe risk signal.
_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)

# Conduct flags that escalate a review to a senior checker (mirrors ComplaintReviewPolicy).
_ESCALATING_FLAGS: frozenset[ConductFlagKind] = frozenset(
    {
        ConductFlagKind.SYSTEMIC_ISSUE,
        ConductFlagKind.REGULATORY_BREACH,
        ConductFlagKind.VULNERABLE_CUSTOMER,
    }
)


def _redact(text: str) -> str:
    """Mask every jurisdiction's national identifiers plus email/phone before the wire."""
    return re.sub(r"\s+", " ", pii_redact(text, _ALL_PATTERNS)).strip()


def _overall_severity(review: ComplaintReview) -> Severity:
    """The review's most severe signal across the categorisation and any conduct flags."""
    present = [review.categorization.severity]
    present.extend(f.severity for f in review.conduct_flags)
    present = [s for s in present if s in _SEVERITY_ORDER]
    if not present:
        return Severity.LOW
    return max(present, key=_SEVERITY_ORDER.index)


def _escalated(review: ComplaintReview) -> bool:
    """Mirror the policy: a high-stakes conduct flag or a HIGH/CRITICAL severity escalates."""
    if any(f.kind in _ESCALATING_FLAGS for f in review.conduct_flags):
        return True
    return _overall_severity(review) in (Severity.HIGH, Severity.CRITICAL)


def _review_citations(review: ComplaintReview) -> list[Citation]:
    out: list[Citation] = list(review.summary.citations)
    out.extend(review.categorization.citations)
    for flag in review.conduct_flags:
        out.extend(flag.citations)
    if review.draft_response is not None:
        out.extend(review.draft_response.citations)
    return out


def _kit_citations(review: ComplaintReview) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for c in _review_citations(review):
        if c.source_id in seen:
            continue
        seen.add(c.source_id)
        out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_redact(c.snippet)))
        if len(out) >= _MAX_CITATIONS:
            break
    return tuple(out)


def review_to_review(review: ComplaintReview, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a complaint review
    escalates.
    """
    categorization = review.categorization
    products = ", ".join(review.summary.products) or "unknown"
    descriptor = (
        f"Complaint review {review.file_id} "
        f"(category={categorization.category.value}, products={products}): "
        f"{review.summary.issue}"
    )
    summary = (
        f"category={categorization.category.value}; "
        f"root_cause_systemic={str(categorization.root_cause.systemic).lower()}; "
        f"conduct_flags={len(review.conduct_flags)}; timeline={len(review.summary.timeline)}"
    )
    severity = _overall_severity(review)
    # Dual control for the strongest band or any escalation (senior-checker conduct flag / HIGH+).
    dual = _escalated(review) or severity in (Severity.HIGH, Severity.CRITICAL)
    return Review(
        action=f"complaint_review:{categorization.category.value}",
        subject=_redact(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_redact(summary),
        severity=severity.value,
        required_approvals=2 if dual else 1,
        sod_group="complaints-maker-checker",
        case_ref=review.file_id,
        citations=_kit_citations(review),
    )
