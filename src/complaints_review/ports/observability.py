"""Observability ports — the A5 (audit/trace) and A4 (eval gate) concerns.

Two of the three boundaries here are re-exported rather than redeclared.
``ObservabilityTracerPort`` and ``TokenUsage`` come from ``hex-service-kit`` and
``EvaluationGatePort`` from ``agent-eval-kit``, for the same reason ``IdentityPort`` is
declared once: sixteen repositories each hand-copied these Protocols and they had already
drifted apart. One had dropped the evaluation port entirely, two had dropped its ``gate``
method and kept only ``evaluate`` (the half that cannot refuse a promotion), and one returned
``str`` from an audit ``record`` that returns ``None`` everywhere else. A Protocol copied into
N repositories is N Protocols, and only one of them gets fixed when a defect is found.

The two ports split across the two commons packages by where their types already live: the
tracer beside the ``TokenUsage`` it reports, the gate beside the ``EvalReport`` it returns.
Both are typing-only imports, so this module costs the offline profile nothing: no
OpenTelemetry, no HTTP client, no cloud SDK.

``AuditSinkPort`` stays declared here on purpose. It is typed in this repo's own vocabulary
(:class:`~complaints_review.domain.models.AuditEvent`, carrying the already-redacted prompt
and response and this service's citations), so it is not a shared shape and has nothing to
converge on.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit, **Cloud Trace
via OpenTelemetry** for reasoning-loop traces (message content capture OFF so PII never
reaches a span), and the **Gen AI evaluation service** for the promotion gate (categorisation
accuracy, groundedness, citation accuracy, PII safety).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort, TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable, already-redacted audit record (WORM)."""
        ...


__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
