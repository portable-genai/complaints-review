"""Pydantic v2 request/response models for the B6 API.

These schemas mirror the frozen domain dataclasses in
:mod:`complaints_review.domain.models` one-for-one, so the HTTP boundary is a thin, typed
projection of the domain : the React/Next.js UI and the CLI consume exactly these shapes.
Each response model exposes a ``from_domain`` classmethod that builds itself from the
corresponding domain object, using :func:`domain.serialization.to_jsonable` where a
nested structure is easiest to project verbatim (enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration service : never on a concrete adapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..domain import models as m
from ..domain.serialization import to_jsonable


# --------------------------------------------------------------------------- #
# Shared citation projection
# --------------------------------------------------------------------------- #
class CitationModel(BaseModel):
    """Provenance attached to a generated claim (mirror of Citation)."""

    source_id: str
    source_type: str
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None

    @classmethod
    def from_domain(cls, citation: m.Citation) -> CitationModel:
        return cls(**to_jsonable(citation))


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class ComplaintFileModel(BaseModel):
    """An inbound complaint / conduct file (mirror of ComplaintFile)."""

    id: str = Field(..., min_length=1)
    customer_ref: str = ""
    product: str = ""
    channel: str = "other"
    received_date: str = ""
    documents: list[str] = Field(default_factory=list)
    narrative: str = ""

    def to_domain(self) -> m.ComplaintFile:
        channel = {c.value: c for c in m.Channel}.get(self.channel.lower(), m.Channel.OTHER)
        return m.ComplaintFile(
            id=self.id,
            customer_ref=self.customer_ref,
            product=self.product,
            channel=channel,
            received_date=self.received_date,
            documents=tuple(self.documents),
            narrative=self.narrative,
        )


class ReviewRequest(BaseModel):
    """Inbound complaint-review request.

    There is intentionally no ``actor`` field: the audit actor and the entitlement
    principals are resolved server-side from the verified :class:`Principal` (identity
    comes from the IAP assertion in secure mode, or a seeded dev persona in local mode),
    never from the request body. Any client-asserted identity is ignored.
    """

    file: ComplaintFileModel


# --------------------------------------------------------------------------- #
# Artifact responses
# --------------------------------------------------------------------------- #
class TimelineEventModel(BaseModel):
    date: str
    event: str


class ComplaintSummaryModel(BaseModel):
    """Structured complaint-file summary (mirror of ComplaintSummary)."""

    issue: str
    products: list[str] = Field(default_factory=list)
    channel: str = "other"
    timeline: list[TimelineEventModel] = Field(default_factory=list)
    parties: list[str] = Field(default_factory=list)
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, summary: m.ComplaintSummary) -> ComplaintSummaryModel:
        return cls(
            issue=summary.issue,
            products=list(summary.products),
            channel=summary.channel.value,
            timeline=[TimelineEventModel(date=t.date, event=t.event) for t in summary.timeline],
            parties=list(summary.parties),
            citations=[CitationModel.from_domain(c) for c in summary.citations],
        )


class RootCauseModel(BaseModel):
    description: str
    systemic: bool = False


class CategorizationModel(BaseModel):
    """Categorisation + root cause + severity (mirror of Categorization)."""

    category: str
    root_cause: RootCauseModel
    severity: str = "medium"
    regulatory_relevance: list[str] = Field(default_factory=list)
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, c: m.Categorization) -> CategorizationModel:
        return cls(
            category=c.category.value,
            root_cause=RootCauseModel(
                description=c.root_cause.description, systemic=c.root_cause.systemic
            ),
            severity=c.severity.value,
            regulatory_relevance=list(c.regulatory_relevance),
            citations=[CitationModel.from_domain(x) for x in c.citations],
        )


class ConductFlagModel(BaseModel):
    """A conduct red flag (mirror of ConductFlag)."""

    kind: str
    severity: str
    detail: str
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, flag: m.ConductFlag) -> ConductFlagModel:
        return cls(
            kind=flag.kind.value,
            severity=flag.severity.value,
            detail=flag.detail,
            citations=[CitationModel.from_domain(c) for c in flag.citations],
        )


class DraftResponseModel(BaseModel):
    """A regulator/customer draft response (mirror of DraftResponse)."""

    body: str
    tone: str = "empathetic-formal"
    citations: list[CitationModel] = Field(default_factory=list)
    requires_human_review: bool = True
    is_draft: bool = True

    @classmethod
    def from_domain(cls, draft: m.DraftResponse) -> DraftResponseModel:
        return cls(
            body=draft.body,
            tone=draft.tone,
            citations=[CitationModel.from_domain(c) for c in draft.citations],
            requires_human_review=draft.requires_human_review,
            is_draft=draft.is_draft,
        )


class ComplaintReviewModel(BaseModel):
    """The full review deliverable (mirror of ComplaintReview)."""

    file_id: str
    summary: ComplaintSummaryModel
    categorization: CategorizationModel
    conduct_flags: list[ConductFlagModel] = Field(default_factory=list)
    draft_response: DraftResponseModel | None = None
    requires_human_review: bool = True
    generated_at: str = ""

    @classmethod
    def from_domain(cls, review: m.ComplaintReview) -> ComplaintReviewModel:
        return cls(
            file_id=review.file_id,
            summary=ComplaintSummaryModel.from_domain(review.summary),
            categorization=CategorizationModel.from_domain(review.categorization),
            conduct_flags=[ConductFlagModel.from_domain(f) for f in review.conduct_flags],
            draft_response=(
                DraftResponseModel.from_domain(review.draft_response)
                if review.draft_response is not None
                else None
            ),
            requires_human_review=review.requires_human_review,
            generated_at=to_jsonable(review.generated_at),
        )


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
class HealthResponse(BaseModel):
    """Liveness/readiness of the service and its active profile."""

    status: str = "ok"
    profile: str = "local"
    region: str = "asia-southeast1"
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "complaints-review"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        data: dict[str, Any] = to_jsonable(card)
        return cls(**data)
