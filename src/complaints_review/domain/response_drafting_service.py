"""ResponseDraftingService — grounded draft regulator/customer response (SPEC §5).

Given a redacted complaint extract, the agreed categorisation, and retrieved policy
passages, this service drafts a :class:`DraftResponse`. The draft is **always** a draft
and always ``requires_human_review=True``: the system never sends it (R1 / P-06). A
human reviewer reads, edits and sends it.

Mirrors the grounded skeleton: render passages -> generate (structured) -> map
source_ids back to retrieved Citations -> assemble a draft. Pure domain code, no Google
Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from . import _grounded as g
from .models import (
    Categorization,
    DraftResponse,
    RetrievedPassage,
)
from .prompts import _CITATION_RULES, DRAFT_RESPONSE_SYSTEM, DRAFT_RESPONSE_USER

_DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "body": {"type": "string"},
        "tone": {"type": "string"},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["body"],
}

#: Prefix stamped on every draft so it is unmistakable that the system has not sent it.
_DRAFT_MARKER = "[DRAFT : not sent. Requires human review and sign-off before sending.]"


class ResponseDraftingService:
    """Draft a regulator/customer response. Signature fixed by SPEC §5."""

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def draft(
        self,
        complaint_text: str,
        categorization: Categorization,
        passages: list[RetrievedPassage],
        tracer: Any | None = None,
    ) -> DraftResponse:
        """Draft a grounded response (always a draft, never sent by the system)."""
        passage_block = g.render_passages(passages)
        system = DRAFT_RESPONSE_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = DRAFT_RESPONSE_USER.format(
            complaint=complaint_text,
            categorization=self._render_categorization(categorization),
            passages=passage_block,
        )
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,
            response_schema=_DRAFT_SCHEMA,
        )
        response = self._llm.generate(request)
        if tracer is not None:
            g.maybe_record_usage(tracer, response)

        parsed = g.parse_structured(response)
        body = str(parsed.get("body") or "").strip()
        if not body:
            body = (
                "We are reviewing your complaint and will respond fully within the "
                "complaint-handling window. A specialist will be in touch."
            )
        tone = str(parsed.get("tone") or "empathetic-formal").strip() or "empathetic-formal"
        citations = g.citations_for_source_ids(
            g.as_str_list(parsed.get("used_source_ids")), passages
        )
        return DraftResponse(
            body=f"{_DRAFT_MARKER}\n\n{body}",
            tone=tone,
            citations=citations,
            requires_human_review=True,
            is_draft=True,
        )

    @staticmethod
    def _render_categorization(categorization: Categorization) -> str:
        relevance = ", ".join(categorization.regulatory_relevance) or "n/a"
        return (
            f"category: {categorization.category.value}; "
            f"severity: {categorization.severity.value}; "
            f"root cause: {categorization.root_cause.description} "
            f"(systemic: {str(categorization.root_cause.systemic).lower()}); "
            f"regulatory relevance: {relevance}"
        )
