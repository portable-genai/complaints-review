"""A2A AgentCard for the B6 Complaints & Conduct File Review service (A3 Governance).

This builds the service's discovery card : the same minimal A2A shape the
``agent-registry`` service stores and serves (SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises exactly the three skills B6 exposes (review_complaint, categorise,
draft_response), mirroring the ADK FunctionTools so a peer agent or the registry sees one
consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

# Skill ids are the stable, machine-facing capability names; they intentionally match the
# FunctionTool callables in ``agent.tools`` so the card and the tool surface stay in lockstep.
SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="review_complaint",
        name="Complaint review",
        description=(
            "Produce a full cited complaint review from a complaint / conduct file: a "
            "structured summary, a categorisation with root cause and conduct flags, and "
            "a draft regulator/customer response. Always human-reviewed; never auto-sent."
        ),
    ),
    AgentSkill(
        id="categorise",
        name="Complaint categorisation",
        description=(
            "Categorise a complaint with root cause, severity, regulatory relevance and "
            "conduct red flags (vulnerable customer, systemic issue, breach, deadline risk)."
        ),
    ),
    AgentSkill(
        id="draft_response",
        name="Draft response",
        description=(
            "Draft a regulator-ready / customer-ready response grounded in policy and "
            "regulation. The draft is never sent by the system : a human reviews and sends it."
        ),
    ),
)

_DESCRIPTION = (
    "Conduct-ops assistant for Complaints and Conduct teams at APAC banks. From a "
    "complaint / conduct file it produces four cited, audited, maker-checker artifacts: a "
    "structured summary, a categorisation with root cause and conduct flags, conduct red "
    "flags, and a draft regulator/customer response (always human-reviewed, never "
    "auto-sent). Built ports-and-adapters on the Gemini Enterprise Agent Platform "
    "(Document AI extraction, A2 governed RAG, Agent Runtime hosting)."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this service."""
    base_url = _resolve_url(settings)
    return AgentCard(
        name="complaints-review",
        description=_DESCRIPTION,
        url=base_url,
        version="0.1.0",
        skills=SKILLS,
        provider="complaints-review",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to asia-southeast1."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://complaints-review.rsk.internal/a2a"
