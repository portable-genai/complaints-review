"""Platform ReviewRouterPort: submit the routed review to human-review-console via ``review-kit``.

Builds the review from the escalated complaint review and submits it to the human-review-console
service intake (``POST /v1/service/reviews``), S2S-authenticated. The human-review-console base URL
comes from the environment (``HUMAN_REVIEW_URL``) and the S2S credentials from this repo's shared
env-var names (``S2S_TOKEN`` / ``S2S_SIGNING_KEY``, the same pair the other platform delegates use).
No cloud SDK is involved (the kit uses stdlib ``urllib`` + wire-compatible S2S headers), so this
module imports cleanly with no GCP SDK; it is bound under the ``gcp`` and ``platform`` profiles
because it makes a real network call to a sibling service.
"""

from __future__ import annotations

from review_kit import ReviewClient

from ...config import Settings
from ...domain.models import ComplaintReview
from ...envread import read_env_setting
from .._review_payload import review_to_review
from ._s2s import SIGNING_KEY_ENV, TOKEN_ENV

_URL_ENV = "HUMAN_REVIEW_URL"


class PlatformReviewRouter:
    """Submit escalated complaint reviews to human-review-console (rule R8) via the shared
    submission client.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def route(
        self, review: ComplaintReview, *, maker: str, tenant: str = ""
    ) -> None:  # pragma: no cover - needs live human-review-console
        # Deliberate collapse: UNSET and SET-AND-EMPTY both resolve to "" and both refuse
        # below. There is no documented default to inherit, because routing a review to a
        # guessed human-review-console host is worse than not routing it, so the closed direction
        # for both
        # states is the same one: refuse to submit.
        base_url = read_env_setting(_URL_ENV).value
        if not base_url:
            raise RuntimeError(f"{_URL_ENV} must be set to route reviews to human-review-console")
        client = ReviewClient(base_url, token_env=TOKEN_ENV, signing_key_env=SIGNING_KEY_ENV)
        client.submit(
            review_to_review(review, maker=maker, tenant=tenant), actor="doc6-complaints-review"
        )
