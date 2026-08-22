"""Domain models for the Complaints & Conduct File Review service (system B6).

This module is the VERTICAL half of the hexagon's core: the complaint and conduct
artifacts a fork rewrites when it retargets this repo at a different document vertical
(the intake file and its channel taxonomy, the document extract, the categorisation and
its root cause, the conduct flags, the draft response, and the ``ComplaintReview``
bundle that ties them together).

The vertical-neutral machinery it is built on : citations and provenance, retrieval,
the LLM envelope, guardrail and redaction verdicts, the audit event, the eval report,
agent cards and tool specs, the shared severity scale and the domain clock : lives in
:mod:`complaints_review.domain.kernel`, which imports nothing from this package. This
module imports the kernel and re-exports every one of those names below, so every
existing ``from complaints_review.domain.models import Citation`` style import site is
unchanged while the dependency arrow points one way only (kernel <- models). See
``tests/unit/test_kernel_boundary.py``, which proves that direction by execution.

Neither module depends on Google Cloud, ADK, FastAPI, or any framework : only the
Python standard library and the shared commons packages. Every adapter (GCP,
remote-platform, or on-prem placeholder) speaks in terms of these types, which is what
lets the managed-service stack be swapped for an on-premise one without touching domain
logic (General Principle P-02, "no vendor lock-in / ports & adapters").

B6 takes a complaint / conduct file (which carries customer PII, so rule R1 applies)
and produces four cited, audited, maker-checker artifacts: a structured summary, a
categorisation (with root cause and conduct flags), conduct red flags, and a draft
regulator-ready / customer-ready response. The draft response is **never** sent by the
system: a human reviews and sends it (P-06).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# The vertical-neutral kernel, re-exported name for name. ``X as X`` is the explicit
# re-export form, so the names stay part of this module's public surface for every
# existing import site and for a type checker, without this module owning them.
from .kernel import (
    AgentCard as AgentCard,
)
from .kernel import (
    AgentSkill as AgentSkill,
)
from .kernel import (
    AuditEvent as AuditEvent,
)
from .kernel import (
    Citation as Citation,
)
from .kernel import (
    Decision as Decision,
)
from .kernel import (
    Direction as Direction,
)
from .kernel import (
    EvalMetricResult as EvalMetricResult,
)
from .kernel import (
    EvalReport as EvalReport,
)
from .kernel import (
    GuardrailCategory as GuardrailCategory,
)
from .kernel import (
    GuardrailFinding as GuardrailFinding,
)
from .kernel import (
    GuardrailVerdict as GuardrailVerdict,
)
from .kernel import (
    IngestResult as IngestResult,
)
from .kernel import (
    LlmMessage as LlmMessage,
)
from .kernel import (
    LlmRequest as LlmRequest,
)
from .kernel import (
    LlmResponse as LlmResponse,
)
from .kernel import (
    RedactionFinding as RedactionFinding,
)
from .kernel import (
    RedactionResult as RedactionResult,
)
from .kernel import (
    RetrievalQuery as RetrievalQuery,
)
from .kernel import (
    RetrievedPassage as RetrievedPassage,
)
from .kernel import (
    Severity as Severity,
)
from .kernel import (
    SourceType as SourceType,
)
from .kernel import (
    StrEnum as StrEnum,
)
from .kernel import (
    ThinkingLevel as ThinkingLevel,
)
from .kernel import (
    TokenUsage as TokenUsage,
)
from .kernel import (
    ToolSpec as ToolSpec,
)
from .kernel import (
    WebCitation as WebCitation,
)
from .kernel import (
    utcnow as utcnow,
)


# --------------------------------------------------------------------------- #
# Complaint intake taxonomy
# --------------------------------------------------------------------------- #
class Channel(StrEnum):
    """The channel a complaint arrived through."""

    BRANCH = "branch"
    CALL_CENTRE = "call_centre"
    EMAIL = "email"
    APP = "app"
    WEB = "web"
    LETTER = "letter"
    SOCIAL = "social"
    REGULATOR = "regulator"  # referred via the regulator / ombudsman
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class DocumentExtract:
    """Structured extraction of one document in the complaint file (Document AI)."""

    document_id: str
    fields: dict[str, str] = field(default_factory=dict)
    text: str = ""
    pages: int = 0


@dataclass(frozen=True, slots=True)
class ComplaintFile:
    """An inbound complaint / conduct file under review.

    Carries customer PII (``customer_ref``, ``narrative``, attached documents), so the
    full R1 safety pipeline (redact then guardrail) runs before any of it reaches a
    model, the knowledge base, a trace span or the audit sink.
    """

    id: str
    customer_ref: str
    product: str
    channel: Channel
    received_date: str  # ISO date the complaint was received (deadline clock starts)
    documents: tuple[str, ...] = ()  # document ids / uris attached to the file
    narrative: str = ""  # the customer's account of the complaint (free text, PII)


# --------------------------------------------------------------------------- #
# Complaint categorisation & conduct
# --------------------------------------------------------------------------- #
class ComplaintCategory(StrEnum):
    """Top-level categorisation of a complaint (drives routing and reporting)."""

    MIS_SELLING = "mis_selling"
    FEES_CHARGES = "fees_charges"
    SERVICE = "service"
    ACCESS = "access"
    CONDUCT = "conduct"
    FRAUD = "fraud"
    OTHER = "other"


class ConductFlagKind(StrEnum):
    """Conduct red flags a reviewer must not miss."""

    VULNERABLE_CUSTOMER = "vulnerable_customer"
    SYSTEMIC_ISSUE = "systemic_issue"
    REGULATORY_BREACH = "regulatory_breach"
    DEADLINE_RISK = "deadline_risk"  # complaint-handling deadline at risk


@dataclass(frozen=True, slots=True)
class RootCause:
    """The underlying cause of the complaint, with a systemic-issue flag."""

    description: str
    systemic: bool = False


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One dated event in the reconstructed timeline of the complaint."""

    date: str  # ISO date of the event
    event: str


@dataclass(frozen=True, slots=True)
class ConductFlag:
    """A conduct red flag raised against the complaint file."""

    kind: ConductFlagKind
    severity: Severity
    detail: str
    citations: tuple[Citation, ...] = ()


# --------------------------------------------------------------------------- #
# The four artifacts B6 produces (bundled into a ComplaintReview)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ComplaintSummary:
    """Structured summary of the complaint file."""

    issue: str
    products: tuple[str, ...] = ()
    channel: Channel = Channel.OTHER
    timeline: tuple[TimelineEvent, ...] = ()
    parties: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class Categorization:
    """The complaint's category, root cause, severity and regulatory relevance."""

    category: ComplaintCategory
    root_cause: RootCause
    severity: Severity = Severity.MEDIUM
    regulatory_relevance: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class DraftResponse:
    """A regulator-ready / customer-ready draft response.

    Always a draft and always human-reviewed: the system never sends it (P-06 / R1).
    """

    body: str
    tone: str = "empathetic-formal"
    citations: tuple[Citation, ...] = ()
    requires_human_review: bool = True
    is_draft: bool = True


@dataclass(frozen=True, slots=True)
class ComplaintReview:
    """The deliverable bundle: summary + categorisation + conduct flags + draft response.

    Always flagged for human review (maker-checker, P-06): a reviewer signs off the
    categorisation and sends the draft response.
    """

    file_id: str
    summary: ComplaintSummary
    categorization: Categorization
    conduct_flags: tuple[ConductFlag, ...] = ()
    draft_response: DraftResponse | None = None
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)
