"""Maker-checker review policy for complaint reviews : General Principle P-06.

B6 is a *decision-support* assistant, never an autonomous approver or sender. P-06
(maker-checker) requires that a human reviews the categorisation and sends the draft
response before either is relied upon. This module centralises that gate so the rules
are auditable in one place.

Policy (SPEC §5):
* A complaint review is **always** consequential: ``ComplaintReview`` and its
  ``DraftResponse`` are always ``requires_human_review=True``, and the draft response is
  never sent by the system (a human sends it).
* Any high-stakes conduct flag : a SYSTEMIC_ISSUE, a REGULATORY_BREACH, or a
  VULNERABLE_CUSTOMER flag : escalates the review (routes it to a senior checker), as
  does a high/critical-severity categorisation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ConductFlag, Severity
from .policy import ComplaintPolicy


@dataclass(frozen=True, slots=True)
class ComplaintReviewPolicy:
    """Maker-checker gate (P-06). Pure decision logic; no side effects."""

    policy: ComplaintPolicy = ComplaintPolicy()

    def requires_review(self) -> bool:
        """A complaint review is consequential : it always requires human review."""
        return True

    def draft_is_sendable(self) -> bool:
        """The system never sends a draft response : a human always sends it (R1/P-06)."""
        return False

    def escalates(
        self,
        conduct_flags: tuple[ConductFlag, ...],
        severity: Severity | None,
    ) -> bool:
        """Whether the review must route to a *senior* checker.

        Escalates on any systemic-issue / regulatory-breach / vulnerable-customer flag,
        or a high/critical-severity categorisation.

        Args:
            conduct_flags: the conduct flags raised against the file.
            severity: the categorisation severity, if any.

        Returns:
            True if the review must be escalated to a senior checker.
        """
        if any(flag.kind in self.policy.escalating_flags for flag in conduct_flags):
            return True
        return severity is not None and severity in self.policy.high_severities
