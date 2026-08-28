"""Vertical-neutral evidence, model-boundary, safety, and audit contracts.

This module OWNS the machinery a fork keeps: citations and provenance, the retrieval
query/passage pair, the LLM envelope, the guardrail and redaction verdicts, the audit
event, the eval report, agent cards and tool specs, the ingest result and the shared
severity scale. The complaint and conduct artifacts (the intake file, the categorisation,
the conduct flags, the draft response, the review bundle) stay in ``models`` as the
replaceable vertical layer.

The split is a DEPENDENCY DIRECTION, not a label. This module imports nothing from
``complaints_review``: only the standard library and the shared commons packages. So a
fork can import the kernel without dragging in the complaint artifacts it is about to
rewrite. ``models`` imports this module and re-exports every name below, which is what
keeps existing import sites unchanged. ``tests/unit/test_kernel_boundary.py`` proves the
direction by execution, in a fresh interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

# The shared value types come from the commons packages rather than being declared here.
# ``TokenUsage`` and the two eval report types were hand-copied into sixteen repositories,
# and by the time anyone compared them they had drifted; re-exporting retires that whole
# class of defect, because there is exactly one definition to change. The eval types are
# imported from the ``agent_eval_kit.report`` SUBMODULE, not the package root: the root
# pulls in ``gate_client``, which needs httpx, and this module promises to be stdlib-only
# apart from the commons themselves.
from agent_eval_kit.report import EvalMetricResult as EvalMetricResult
from agent_eval_kit.report import EvalReport as EvalReport
from hex_service_kit import StrEnum as StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage


def utcnow() -> datetime:
    """Timezone-aware UTC now : the single clock the domain uses."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Severity : the shared scale every vertical judgement is expressed on
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# --------------------------------------------------------------------------- #
# Citation & retrieval (governed RAG via A2)
# --------------------------------------------------------------------------- #
class SourceType(StrEnum):
    """Where a citation points : the complaint file itself, policy, or regulation."""

    COMPLAINT_FILE = "complaint_file"
    POLICY = "policy"
    REGULATION = "regulation"


@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to every generated claim.

    Page-level citation is a hard requirement: a categorisation or a draft response
    must point to the exact source (policy clause, regulatory paragraph, or the page of
    the complaint file) so a conduct/compliance reviewer can verify it.
    """

    source_id: str
    source_type: SourceType
    title: str
    url: str = ""
    page: int | None = None
    snippet: str = ""
    score: float | None = None


@dataclass(frozen=True, slots=True)
class RetrievedPassage:
    text: str
    citation: Citation
    score: float = 0.0
    # ACL tags this passage carries in the governed store. Empty == public (visible to
    # all). A tagged passage (e.g. ``("tenant:demo-bank",)``) is returned only to a query
    # whose ``RetrievalQuery.acl_principals`` hold EVERY tag (subset match, fail-closed),
    # so tenant-tagged evidence never crosses a tenant boundary in retrieval.
    acl_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 10
    # ACL principals scoping a governed A2 search to what this actor may read.
    acl_principals: tuple[str, ...] = ()
    # Structured filters resolved by the adapter (e.g. {"source_type": "policy"}).
    filters: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WebCitation:
    """Provenance for a public-web grounded fact (secondary, cross-border)."""

    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class IngestResult:
    document_id: str
    chunks: int = 0
    status: str = "indexed"
    ok: bool = True
    detail: str = ""


# --------------------------------------------------------------------------- #
# Generation (LLM)
# --------------------------------------------------------------------------- #
class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.0  # omitted at a call site means this value; it must not sample
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# ``TokenUsage`` was declared in ``models``: three ``int`` fields defaulting to zero,
# byte-identical to the copy in fifteen sibling repositories. It is now
# ``hex_service_kit.observability.TokenUsage``, imported at the top of this module and
# re-exported under the same name, so every call site is unchanged and there is one
# definition left to drift.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    web_citations: tuple[WebCitation, ...] = ()
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Safety (guardrail + PII redaction) : A1 Guardrail Gateway concerns
# --------------------------------------------------------------------------- #
class GuardrailCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    SENSITIVE_DATA = "sensitive_data"
    MALICIOUS_URL = "malicious_url"
    HATE = "hate"
    HARASSMENT = "harassment"
    SEXUAL = "sexual"
    DANGEROUS = "dangerous"
    OTHER = "other"


class Direction(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


@dataclass(frozen=True, slots=True)
class GuardrailFinding:
    category: GuardrailCategory
    confidence: str  # e.g. "low" | "medium" | "high"
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    allowed: bool
    direction: Direction
    findings: tuple[GuardrailFinding, ...] = ()
    # Text after any inline sanitisation the guardrail applied (may equal input).
    sanitized_text: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RedactionFinding:
    info_type: str  # e.g. "PERSON_NAME", "SG_NRIC_FIN", "CREDIT_CARD_NUMBER"
    count: int = 1


@dataclass(frozen=True, slots=True)
class RedactionResult:
    text: str  # de-identified text safe to send to the model / audit log
    findings: tuple[RedactionFinding, ...] = ()

    @property
    def redacted(self) -> bool:
        return bool(self.findings)


# --------------------------------------------------------------------------- #
# Audit & observability : A5 Observability, Audit & FinOps concerns
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one review interaction.

    Prompt and response are stored **already redacted** (P-04): customer PII is removed
    at the boundary before it is ever written to the audit sink or a trace span.
    """

    action: str  # "review" | "summary" | "categorise" | "draft_response"
    actor: str  # authenticated user / service identity
    decision: Decision
    redacted_prompt: str
    redacted_response: str
    citations: tuple[Citation, ...] = ()
    resource: str = "complaints-review"
    trace_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Evaluation gate : A4 AI Quality & Model-Risk concerns
# --------------------------------------------------------------------------- #
# ``EvalMetricResult`` and ``EvalReport`` were declared in ``models`` and are now
# ``agent_eval_kit.report``'s, imported at the top of this module and re-exported under the
# same names. The move was checked field by field before it was made:
#
# * the fail-closed ``passed`` rule is IDENTICAL, ``n_examples > 0 and bool(results) and
#   all(...)``. ``all(())`` is vacuously True, so a report that scored nothing would report
#   PASSED and ``eval/run_eval.py`` exits 0 on this property. Re-exporting a weaker rule
#   would have silently reopened that fail-open, so it was the first thing compared; see
#   ``tests/unit/test_eval_report_gate.py``, which still holds the rule to its behaviour.
# * the commons type is purely ADDITIVE: ``run_id``, ``dataset_version``, ``dataset_digest``,
#   ``evaluator``, ``schema_version``, ``trace_id``, ``correlation_id``, ``artifact_refs`` and
#   ``attested`` are all defaulted, so every existing constructor still compiles, and the
#   platform adapter now returns that attested evidence instead of dropping it.
#
# Neither type is persisted anywhere in this repo (no ``to_jsonable``, no audit row, no API
# response schema), so nothing on disk or on the wire changed shape.


# --------------------------------------------------------------------------- #
# Governance : A3 Agent Registry & Governance concerns (A2A AgentCard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "complaints-review"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


__all__ = [
    "AgentCard",
    "AgentSkill",
    "AuditEvent",
    "Citation",
    "Decision",
    "Direction",
    "EvalMetricResult",
    "EvalReport",
    "GuardrailCategory",
    "GuardrailFinding",
    "GuardrailVerdict",
    "IngestResult",
    "LlmMessage",
    "LlmRequest",
    "LlmResponse",
    "RedactionFinding",
    "RedactionResult",
    "RetrievalQuery",
    "RetrievedPassage",
    "Severity",
    "SourceType",
    "StrEnum",
    "ThinkingLevel",
    "TokenUsage",
    "ToolSpec",
    "WebCitation",
    "utcnow",
]
