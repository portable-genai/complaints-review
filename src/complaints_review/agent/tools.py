"""ADK FunctionTools that expose the B6 domain service to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the ComplaintReviewService
from a :class:`~complaints_review.config.Container` (so every port is bound to the adapter
selected by the active profile), invokes the service, and returns a JSON-safe dict via
:func:`~complaints_review.domain.serialization.to_jsonable`.

Design notes
------------
* The domain service owns orchestration (redact -> guardrail -> extract -> retrieve ->
  summarise -> categorise -> draft -> guardrail -> audit; SPEC §5). These tools add **no**
  business logic of their own : the model decides *which* artifact to produce, the service
  decides *how*. The draft response is never sent by the system.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The
  plain Python tool callables are importable and unit-testable without ADK at all.
* Every callable carries a precise type-hinted signature and a docstring: ADK derives the
  tool's name, description and JSON parameter schema from them, so the wording here is part
  of the agent's contract surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container
from ..domain.models import Channel, ComplaintFile

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool


# The model invokes a tool on behalf of an authenticated end user. The deployed Agent
# Runtime injects the real identity (via session state); until then we record a stable
# service identity so every audit row has an actor.
_DEFAULT_ACTOR = "complaints-review-agent"

_CHANNEL_BY_VALUE: dict[str, Channel] = {c.value: c for c in Channel}


def _container(settings: Settings | None) -> Container:
    """Build the DI container, honouring an optionally-injected ``Settings``."""
    return build_container(settings)


def _file(
    file_id: str,
    narrative: str,
    product: str,
    channel: str,
    received_date: str,
    customer_ref: str,
) -> ComplaintFile:
    return ComplaintFile(
        id=file_id,
        customer_ref=customer_ref,
        product=product,
        channel=_CHANNEL_BY_VALUE.get(channel.lower(), Channel.OTHER),
        received_date=received_date,
        narrative=narrative,
    )


def review_complaint(
    file_id: str,
    narrative: str,
    product: str = "",
    channel: str = "other",
    received_date: str = "",
    customer_ref: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Produce a full cited complaint review for a complaint / conduct file.

    Returns a ``ComplaintReview`` (summary, categorisation with root cause and conduct
    flags, and a draft regulator/customer response). The review is always flagged for
    human review and the draft response is never sent by the system (P-06 / R1).

    Args:
      file_id: The complaint file identifier.
      narrative: The customer's account of the complaint (free text; redacted at boundary).
      product: The product the complaint is about.
      channel: The channel the complaint arrived through.
      received_date: ISO date the complaint was received (the deadline clock).
      customer_ref: Pseudonymous customer reference.
      actor: Authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe ``ComplaintReview`` dict.
    """
    from ..domain.serialization import to_jsonable
    from ..domain.services import ComplaintReviewService

    c = _container(settings)
    service = ComplaintReviewService(
        extraction=c.extraction,
        knowledge_base=c.knowledge_base,
        llm=c.llm,
        guardrail=c.guardrail,
        redaction=c.redaction,
        tracer=c.tracer,
        audit=c.audit,
        review_router=c.review_router,
    )
    file = _file(file_id, narrative, product, channel, received_date, customer_ref)
    return to_jsonable(service.review(file, actor))


def categorise(
    file_id: str,
    narrative: str,
    product: str = "",
    channel: str = "other",
    received_date: str = "",
    customer_ref: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Categorise a complaint with root cause, severity and conduct flags.

    Returns the ``Categorization`` from a full review (a human reviews it before it is
    relied upon, P-06).

    Args:
      file_id: The complaint file identifier.
      narrative: The customer's account of the complaint (redacted at boundary).
      product: The product the complaint is about.
      channel: The channel the complaint arrived through.
      received_date: ISO date the complaint was received.
      customer_ref: Pseudonymous customer reference.
      actor: Authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe ``Categorization`` dict.
    """
    from ..domain.serialization import to_jsonable
    from ..domain.services import ComplaintReviewService

    c = _container(settings)
    service = ComplaintReviewService(
        extraction=c.extraction,
        knowledge_base=c.knowledge_base,
        llm=c.llm,
        guardrail=c.guardrail,
        redaction=c.redaction,
        tracer=c.tracer,
        audit=c.audit,
    )
    file = _file(file_id, narrative, product, channel, received_date, customer_ref)
    return to_jsonable(service.review(file, actor).categorization)


def draft_response(
    file_id: str,
    narrative: str,
    product: str = "",
    channel: str = "other",
    received_date: str = "",
    customer_ref: str = "",
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Draft a regulator/customer response grounded in policy (a draft, never sent).

    Returns a ``DraftResponse`` flagged for human review. The system never sends it : a
    human reviews and sends it (P-06 / R1).

    Args:
      file_id: The complaint file identifier.
      narrative: The customer's account of the complaint (redacted at boundary).
      product: The product the complaint is about.
      channel: The channel the complaint arrived through.
      received_date: ISO date the complaint was received.
      customer_ref: Pseudonymous customer reference.
      actor: Authenticated user / service identity the request is made for.

    Returns:
      A JSON-safe ``DraftResponse`` dict.
    """
    from ..domain.serialization import to_jsonable
    from ..domain.services import ComplaintReviewService

    c = _container(settings)
    service = ComplaintReviewService(
        extraction=c.extraction,
        knowledge_base=c.knowledge_base,
        llm=c.llm,
        guardrail=c.guardrail,
        redaction=c.redaction,
        tracer=c.tracer,
        audit=c.audit,
    )
    file = _file(file_id, narrative, product, channel, received_date, customer_ref)
    return to_jsonable(service.draft_response(file, actor))


# The plain callables, in stable order, so the agent layer and tests share one list.
TOOL_FUNCTIONS = (
    review_complaint,
    categorise,
    draft_response,
)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
