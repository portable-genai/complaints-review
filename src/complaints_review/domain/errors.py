"""Domain exceptions for the Complaints & Conduct File Review service (system B6).

Pure-Python exception hierarchy raised by the orchestration services. The domain layer
never imports Google Cloud, ADK, or any framework : these errors let callers (API, CLI,
the Agent Runtime adapter) react to domain-level failures without coupling to any
vendor SDK error type.
"""

from __future__ import annotations


class ComplaintsError(Exception):
    """Base class for all domain-level errors raised by B6 services."""


class GuardrailBlockedError(ComplaintsError):
    """Raised/flagged when the A1 guardrail blocks an input or output.

    The review pipeline runs the full R1 safety pipeline over a complaint file that
    carries customer PII; a blocked input or output raises this rather than yielding a
    partial review of unsafe content.
    """


class RetrievalEmptyError(ComplaintsError):
    """Raised when governed retrieval returns no policy/regulatory passages.

    Categorisation and the draft response must be grounded; an empty corpus is treated
    as a hard error so the service never emits an ungrounded conduct decision.
    """


class ExtractionFailedError(ComplaintsError):
    """Raised when a complaint document could not be extracted by the parser."""


class AccessDeniedError(ComplaintsError):
    """Raised when a verified principal is not entitled to a complaint file.

    The ``complaint:<id>`` retrieval principal and the ``tenant:<t>`` partition are
    derived server-side from the verified Principal (see ``domain/entitlements.py``),
    never from a client-supplied field; a failed entitlement check maps to HTTP 403 at
    the API layer so an unentitled caller gets a clean denial rather than another
    tenant's evidence.
    """
