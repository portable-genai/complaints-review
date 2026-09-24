"""FastAPI dependency wiring for the B6 Complaints & Conduct File Review service.

This module builds a single, process-wide :class:`~complaints_review.config.Container`
(the ports-and-adapters registry) and assembles the ComplaintReviewService from the
Container's port instances. The Container is created lazily on first access so importing
this module : and therefore the FastAPI app : never touches Google Cloud: a unit test or
the on-prem profile can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. The service takes *explicit
port instances* in its constructor (SPEC §5), so the wiring here is the single place that
knows which ports the service needs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from ..adapters.controls import DisclosingRedaction, RecordingReviewRouter
from ..config import Container, Settings, build_container
from ..domain.models import ConductFlagKind, Severity
from ..domain.policy import ComplaintPolicy
from ..domain.services import ComplaintReviewService


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use.

    Cached for the lifetime of the process so every request shares one set of adapter
    instances (and their cached clients). ``Settings.load()`` reads
    ``config/settings.yaml`` with ``${ENV_VAR}`` interpolation and selects the profile.
    """
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, models...)."""
    return get_container().settings


# --------------------------------------------------------------------------- #
# Service factory : assemble the review service from the Container's ports.
# Constructor argument order mirrors SPEC §5 exactly.
# --------------------------------------------------------------------------- #
def get_request_redaction() -> DisclosingRedaction:
    """The redaction adapter for ONE request, wrapped so the response can disclose a change.

    FastAPI resolves a dependency once per request, so the route and the service it builds
    receive the same wrapper and the route reads what the service's redaction did.
    """
    return DisclosingRedaction(get_container().redaction)


def get_request_review_router() -> RecordingReviewRouter:
    """The review router for ONE request, wrapped so the response reports the hand-off."""
    return RecordingReviewRouter(get_container().review_router)


#: Injected by FastAPI; ``None`` when a getter is called directly, which binds the
#: container's adapters unwrapped.
RequestRedaction = Annotated[DisclosingRedaction | None, Depends(get_request_redaction)]
RequestReviewRouter = Annotated[RecordingReviewRouter | None, Depends(get_request_review_router)]


def get_review_service(
    redaction: RequestRedaction = None, review_router: RequestReviewRouter = None
) -> ComplaintReviewService:
    """ComplaintReviewService(extraction, knowledge_base, llm, guardrail, redaction, ...)."""
    return build_review_service(get_container(), redaction=redaction, review_router=review_router)


def build_review_service(
    container: Container, *, redaction: Any = None, review_router: Any = None
) -> ComplaintReviewService:
    """Assemble a :class:`ComplaintReviewService` from an explicit Container.

    ``redaction`` and ``review_router`` replace the container's adapters for this one service,
    which is how a caller hands it the per-call wrappers and reports what they saw afterwards.
    """
    configured = container.settings.policy
    policy = ComplaintPolicy(
        deadline_days=configured.deadline_days,
        vulnerability_keywords=configured.vulnerability_keywords,
        escalating_flags=frozenset(ConductFlagKind(value) for value in configured.escalating_flags),
        high_severities=frozenset(Severity(value) for value in configured.high_severities),
    )
    return ComplaintReviewService(
        extraction=container.extraction,
        knowledge_base=container.knowledge_base,
        llm=container.llm,
        guardrail=container.guardrail,
        redaction=redaction or container.redaction,
        tracer=container.tracer,
        audit=container.audit,
        review_router=review_router or container.review_router,
        complaint_policy=policy,
    )


def create_app():
    """Application factory used by uvicorn (``--factory``) and the CLI ``serve`` command."""
    from .app import app

    return app
