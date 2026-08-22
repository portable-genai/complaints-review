"""Ports — the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` so adapters need only structural conformance and
contract tests can verify any adapter (GCP, remote-platform, or on-prem placeholder)
satisfies the same contract.
"""

from .extraction import DocumentExtractionPort
from .generation import LLMPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import IdentityPort
from .knowledge_base import KnowledgeBaseClientPort
from .observability import (
    AuditSinkPort,
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .review_router import ReviewRouterPort
from .safety import GuardrailPort, PIIRedactionPort

__all__ = [
    "DocumentExtractionPort",
    "KnowledgeBaseClientPort",
    "LLMPort",
    "GuardrailPort",
    "PIIRedactionPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "EvaluationGatePort",
    "TokenUsage",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "ReviewRouterPort",
]
