"""CategorizationService — category, root cause and conduct flags (SPEC §5).

Given a redacted complaint extract and retrieved policy/regulatory passages, this
service produces a grounded :class:`Categorization` (category + root cause + severity +
regulatory relevance) and a list of :class:`ConductFlag`. Conduct flags come from two
sources that are merged:

* the LLM, which proposes flags from the file and the cited policy; and
* a **deterministic policy** that raises mandatory flags from hard signals : a
  vulnerable-customer keyword in the narrative forces a VULNERABLE_CUSTOMER flag, and a
  breach of the complaint-handling deadline forces a DEADLINE_RISK flag. The
  deterministic flags are authoritative : they cannot be removed by the model.

Mirrors the grounded skeleton: render passages -> generate (structured) -> map
source_ids back to retrieved Citations -> merge deterministic flags. Pure domain code,
no Google Cloud / ADK imports.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from . import _grounded as g
from .models import (
    Categorization,
    Citation,
    ComplaintFile,
    ConductFlag,
    ConductFlagKind,
    RetrievedPassage,
    RootCause,
    Severity,
)
from .policy import ComplaintPolicy
from .prompts import _CITATION_RULES, CATEGORIZE_SYSTEM, CATEGORIZE_USER

_CATEGORIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": [
                "mis_selling",
                "fees_charges",
                "service",
                "access",
                "conduct",
                "fraud",
                "other",
            ],
        },
        "root_cause": {
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "systemic": {"type": "boolean"},
            },
            "required": ["description", "systemic"],
        },
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "regulatory_relevance": {"type": "array", "items": {"type": "string"}},
        "conduct_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": [
                            "vulnerable_customer",
                            "systemic_issue",
                            "regulatory_breach",
                            "deadline_risk",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "detail": {"type": "string"},
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "severity", "detail"],
            },
        },
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["category", "root_cause", "severity"],
}


class CategorizationService:
    """Categorise a complaint and raise conduct flags. Signature fixed by SPEC §5."""

    def __init__(
        self, llm: Any, knowledge_base: Any, policy: ComplaintPolicy | None = None
    ) -> None:
        self._llm = llm
        self._knowledge_base = knowledge_base
        self._policy = policy or ComplaintPolicy()

    def categorize(
        self,
        file: ComplaintFile,
        complaint_text: str,
        passages: list[RetrievedPassage],
        tracer: Any | None = None,
        now: date | None = None,
    ) -> tuple[Categorization, tuple[ConductFlag, ...]]:
        """Return the grounded categorisation and the merged conduct flags."""
        passage_block = g.render_passages(passages)
        system = CATEGORIZE_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = CATEGORIZE_USER.format(complaint=complaint_text, passages=passage_block)
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,
            response_schema=_CATEGORIZE_SCHEMA,
        )
        response = self._llm.generate(request)
        if tracer is not None:
            g.maybe_record_usage(tracer, response)

        parsed = g.parse_structured(response)
        categorization = self._build_categorization(parsed, passages)
        llm_flags = self._build_llm_flags(parsed, passages)
        deterministic_flags = self._deterministic_flags(file, complaint_text, now)
        flags = self._merge_flags(deterministic_flags, llm_flags)
        return categorization, flags

    # ------------------------------------------------------------------ #
    # LLM-derived categorisation
    # ------------------------------------------------------------------ #
    def _build_categorization(
        self, parsed: dict[str, Any], passages: list[RetrievedPassage]
    ) -> Categorization:
        raw_cause = parsed.get("root_cause")
        if isinstance(raw_cause, dict):
            root_cause = RootCause(
                description=str(raw_cause.get("description") or "").strip(),
                systemic=bool(raw_cause.get("systemic", False)),
            )
        else:
            root_cause = RootCause(description=str(raw_cause or "").strip(), systemic=False)
        return Categorization(
            category=g.coerce_category(parsed.get("category")),
            root_cause=root_cause,
            severity=g.coerce_severity(parsed.get("severity")),
            regulatory_relevance=tuple(g.as_str_list(parsed.get("regulatory_relevance"))),
            citations=g.citations_for_source_ids(
                g.as_str_list(parsed.get("used_source_ids")), passages
            ),
        )

    def _build_llm_flags(
        self, parsed: dict[str, Any], passages: list[RetrievedPassage]
    ) -> list[ConductFlag]:
        raw_flags = parsed.get("conduct_flags")
        if not isinstance(raw_flags, list):
            return []
        out: list[ConductFlag] = []
        for raw in raw_flags:
            if not isinstance(raw, dict):
                continue
            kind = g.coerce_flag_kind(raw.get("kind"))
            if kind is None:
                continue
            out.append(
                ConductFlag(
                    kind=kind,
                    severity=g.coerce_severity(raw.get("severity")),
                    detail=str(raw.get("detail") or "").strip(),
                    citations=g.citations_for_source_ids(
                        g.as_str_list(raw.get("used_source_ids")), passages
                    ),
                )
            )
        return out

    # ------------------------------------------------------------------ #
    # Deterministic, mandatory conduct flags (authoritative)
    # ------------------------------------------------------------------ #
    def _deterministic_flags(
        self, file: ComplaintFile, complaint_text: str, now: date | None
    ) -> list[ConductFlag]:
        flags: list[ConductFlag] = []
        lowered = complaint_text.lower()
        hit = next((kw for kw in self._policy.vulnerability_keywords if kw in lowered), None)
        if hit is not None:
            flags.append(
                ConductFlag(
                    kind=ConductFlagKind.VULNERABLE_CUSTOMER,
                    severity=Severity.HIGH,
                    detail=(
                        "Narrative contains a vulnerability signal "
                        f"('{hit}'); handle under the vulnerable-customer policy."
                    ),
                )
            )
        if self._deadline_breached(file, now):
            flags.append(
                ConductFlag(
                    kind=ConductFlagKind.DEADLINE_RISK,
                    severity=Severity.HIGH,
                    detail=(
                        "The complaint is at or beyond the "
                        f"{self._policy.deadline_days}-day complaint-handling window; "
                        "a holding or final response is overdue."
                    ),
                )
            )
        return flags

    def _deadline_breached(self, file: ComplaintFile, now: date | None) -> bool:
        try:
            received = date.fromisoformat(file.received_date)
        except (ValueError, TypeError):
            return False
        today = now or date.today()
        return (today - received).days >= self._policy.deadline_days

    @staticmethod
    def _merge_flags(
        deterministic: list[ConductFlag], llm_flags: list[ConductFlag]
    ) -> tuple[ConductFlag, ...]:
        """Deterministic flags win; LLM flags of a kind already set are dropped."""
        seen_kinds = {flag.kind for flag in deterministic}
        merged = list(deterministic)
        for flag in llm_flags:
            if flag.kind not in seen_kinds:
                seen_kinds.add(flag.kind)
                merged.append(flag)
        return tuple(merged)

    @staticmethod
    def _all_citations(
        categorization: Categorization, flags: tuple[ConductFlag, ...]
    ) -> tuple[Citation, ...]:
        out: list[Citation] = list(categorization.citations)
        for flag in flags:
            out.extend(flag.citations)
        return tuple(out)
