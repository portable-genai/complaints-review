"""Bank-owned deterministic complaint policy with reference defaults."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ConductFlagKind, Severity


@dataclass(frozen=True, slots=True)
class ComplaintPolicy:
    """Consequential thresholds and classifications supplied by the adopter."""

    deadline_days: int = 21
    vulnerability_keywords: tuple[str, ...] = (
        "vulnerable",
        "bereave",
        "bereaved",
        "disab",
        "mental health",
        "illness",
        "terminal",
        "elderly",
        "dementia",
        "financial hardship",
        "hardship",
        "distress",
        "suicid",
    )
    escalating_flags: frozenset[ConductFlagKind] = frozenset(
        {
            ConductFlagKind.SYSTEMIC_ISSUE,
            ConductFlagKind.REGULATORY_BREACH,
            ConductFlagKind.VULNERABLE_CUSTOMER,
        }
    )
    high_severities: frozenset[Severity] = frozenset({Severity.HIGH, Severity.CRITICAL})

    def __post_init__(self) -> None:
        if self.deadline_days <= 0:
            raise ValueError("deadline_days must be positive")
        if not self.vulnerability_keywords:
            raise ValueError("vulnerability_keywords must not be empty")
