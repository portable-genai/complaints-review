"""Generation port — LLM text/reasoning for summarise, categorise and draft.

Primary GCP adapter: Gemini models on the Gemini Enterprise Agent Platform
(``gemini-3.5-flash`` for reasoning, ``gemini-3.1-flash-lite`` for triage). The service
uses the LLM to summarise a complaint file, propose a categorisation with root cause,
and draft a regulator/customer response grounded in retrieved policy.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import LlmRequest, LlmResponse


@runtime_checkable
class LLMPort(Protocol):
    def generate(self, request: LlmRequest) -> LlmResponse:
        """Generate a completion for ``request`` using the configured model."""
        ...

    def classify(self, text: str, labels: list[str]) -> str:
        """Cheap single-label classification (triage/routing tier model)."""
        ...
