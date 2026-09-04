"""Local ReviewRouterPort: enqueue the routed review to an in-memory outbox (no live
human-review-console).

Exercises the R8 routing path offline: an escalated complaint review is converted to a review and
enqueued (the same transactional outbox the platform adapter flushes to human-review-console), so
tests and the offline demo can assert that an escalation is routed without a running console.
"""

from __future__ import annotations

from review_kit import InMemoryOutbox

from ...config import Settings
from ...domain.models import ComplaintReview
from .._review_payload import review_to_review


class LocalReviewRouter:
    """Record routed reviews in an in-memory outbox for the SDK-free ``local`` profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._outbox = InMemoryOutbox()

    def route(self, review: ComplaintReview, *, maker: str, tenant: str = "") -> None:
        self._outbox.enqueue(
            review_to_review(review, maker=maker, tenant=tenant), actor="complaints-review"
        )

    @property
    def outbox(self) -> InMemoryOutbox:
        """Expose the outbox for inspection in tests and the demo."""
        return self._outbox
