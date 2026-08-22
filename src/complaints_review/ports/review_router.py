"""ReviewRouterPort: the boundary that routes an escalated complaint review to Hrz7 (rule R8).

Every complaint review is consequential decision-support and always requires human review (maker-
checker, P-06): the assistant is the maker, a qualified conduct/compliance reviewer is the checker.
Rule R8 says a producer that sets ``requires_human_review`` MUST route the item to the Hrz7 Human-
Review & Maker-Checker Console rather than terminate the escalation in a per-repo boolean. This
port is that hand-off. The domain stays pure: the adapter (not this port) depends on the shared
``review-kit`` client and does the S2S submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ComplaintReview


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, review: ComplaintReview, *, maker: str, tenant: str = "") -> None:
        """Route an escalated review to Hrz7 for human review (idempotent per file is ideal)."""
        ...
