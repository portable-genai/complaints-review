"""Local LLM adapter (LLMPort) : a deterministic, schema-driven generator.

The ``local`` profile's stand-in for **Gemini**: no model, no network, fully
reproducible. It reads ``request.response_schema`` (the JSON schema the calling service
asks for) and emits a deterministic JSON object whose keys match it, including
``used_source_ids`` mapped from the source-id headers present in the rendered passage
block, plus a plausible ``classify``. There is no Google emulator for Gemini, so this
path is unconditional and imports no google-cloud package.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a test fixture, so
the in-memory implementation lives once under ``adapters/local`` and drives both the offline
tests and the CLI. B6
declares three distinct artifact schemas (summary, categorisation, draft response); the
adapter inspects the declared top-level properties to emit the right shape for each.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import Settings
from ...domain.models import (
    LlmRequest,
    LlmResponse,
    TokenUsage,
)

# The rendered passage block keys each source with ``[source_id p.N]`` headers; recover
# the ids the service actually grounded on so every artifact cites only retrieved sources.
_SOURCE_HEADER_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]*?)(?:\s+p\.[^\]]+)?\]")


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


class LocalDeterministicLLMAdapter:
    """Deterministic LLM whose ``generate`` returns JSON matching the request schema.

    The body is shaped from ``request.response_schema``: B6's categorisation, draft and
    summary schemas are distinct, so the adapter inspects the declared top-level
    properties to emit the right shape. Every payload references the source ids actually
    present in the rendered passage block via ``used_source_ids`` so the services map
    page-level citations to retrieved passages.
    """

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.1-flash-lite"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        source_ids = self._source_ids_from_request(request)
        body = self._body_for_schema(request.response_schema, source_ids)
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=request.model or self._reasoning_model,
            web_citations=(),
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (the services only use this for routing).
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    def _source_ids_from_request(self, request: LlmRequest) -> list[str]:
        user = ""
        for message in reversed(request.messages):
            if message.role == "user":
                user = message.content
                break
        seen: list[str] = []
        for sid in _SOURCE_HEADER_RE.findall(user):
            if sid not in seen:
                seen.append(sid)
        return seen

    def _body_for_schema(self, schema: dict | None, source_ids: list[str]) -> dict[str, Any]:
        props = set(_schema_properties(schema))
        sid = list(source_ids)
        if "category" in props:  # categorisation
            return {
                "category": "mis_selling",
                "root_cause": {
                    "description": "Product sold without a suitability assessment.",
                    "systemic": False,
                },
                "severity": "high",
                "regulatory_relevance": ["fair-dealing", "suitability"],
                "conduct_flags": [
                    {
                        "kind": "regulatory_breach",
                        "severity": "high",
                        "detail": "Possible breach of fair-dealing obligations.",
                        "used_source_ids": sid,
                    }
                ],
                "used_source_ids": sid,
            }
        if "body" in props:  # draft response
            return {
                "body": (
                    "Thank you for raising your complaint. We have reviewed the sale of "
                    "the product and will respond fully within the complaint-handling "
                    "window. You may escalate to the relevant ombudsman if unsatisfied."
                ),
                "tone": "empathetic-formal",
                "used_source_ids": sid,
            }
        # summary (default flat shape)
        return {
            "issue": "Customer disputes the suitability of a structured investment product.",
            "products": ["structured investment product"],
            "channel": "branch",
            "timeline": [{"date": "2026-06-01", "event": "Complaint received at branch."}],
            "parties": ["customer", "branch relationship manager"],
            "used_source_ids": sid,
        }
