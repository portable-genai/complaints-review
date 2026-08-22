"""Shared grounded retrieve-reason-cite routine (private to the domain layer).

The B6 sub-services (summary, categorisation, draft response) share the same skeleton:
render the retrieved policy/regulatory passages into the prompt context, call the LLM
with a structured-output schema, defensively parse the JSON, and map the model's
``used_source_ids`` back to the retrieved passages' ``Citation`` objects (preserving
page provenance).

This module factors out that machinery (plus the enum coercions and the LlmRequest
builder) so each service keeps the exact constructor and method signature mandated by
SPEC §5 while sharing one well-tested core. It is ``_``-prefixed and not part of the
public domain API.

Pure domain code: talks only to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

import json
from typing import Any

from .models import (
    Citation,
    ComplaintCategory,
    ConductFlagKind,
    LlmMessage,
    LlmRequest,
    RetrievalQuery,
    RetrievedPassage,
    Severity,
    ThinkingLevel,
)
from .prompts import PASSAGE_BLOCK

#: Severity rank for picking the "highest" severity across flags.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

_SEVERITY_BY_VALUE: dict[str, Severity] = {s.value: s for s in Severity}
_CATEGORY_BY_VALUE: dict[str, ComplaintCategory] = {c.value: c for c in ComplaintCategory}
_FLAG_KIND_BY_VALUE: dict[str, ConductFlagKind] = {k.value: k for k in ConductFlagKind}


def coerce_severity(value: Any, default: Severity = Severity.MEDIUM) -> Severity:
    """Map a model-emitted severity string to the ``Severity`` enum defensively."""
    if isinstance(value, Severity):
        return value
    if isinstance(value, str):
        return _SEVERITY_BY_VALUE.get(value.strip().lower(), default)
    return default


def coerce_category(
    value: Any, default: ComplaintCategory = ComplaintCategory.OTHER
) -> ComplaintCategory:
    """Map a model-emitted category string to the ``ComplaintCategory`` enum."""
    if isinstance(value, ComplaintCategory):
        return value
    if isinstance(value, str):
        return _CATEGORY_BY_VALUE.get(value.strip().lower(), default)
    return default


def coerce_flag_kind(value: Any) -> ConductFlagKind | None:
    """Map a model-emitted conduct-flag kind to the enum, or None if unknown."""
    if isinstance(value, ConductFlagKind):
        return value
    if isinstance(value, str):
        return _FLAG_KIND_BY_VALUE.get(value.strip().lower())
    return None


def highest_severity(severities: list[Severity]) -> Severity | None:
    """Return the most severe entry, or None for an empty list."""
    if not severities:
        return None
    return max(severities, key=lambda s: _SEVERITY_RANK[s])


def render_passages(passages: list[RetrievedPassage]) -> str:
    """Render retrieved passages into the numbered context block for the prompt.

    Each block is keyed by ``source_id`` and page so the model can echo
    ``[source_id p.N]`` citations exactly. Page is rendered as ``?`` when unknown so
    the model emits ``[source_id]`` rather than inventing a page.
    """
    if not passages:
        return "(no passages were retrieved)"
    blocks: list[str] = []
    for p in passages:
        c = p.citation
        page = str(c.page) if c.page is not None else "?"
        blocks.append(
            PASSAGE_BLOCK.format(
                source_id=c.source_id,
                page=page,
                source_type=c.source_type.value,
                title=c.title,
                text=p.text.strip(),
            )
        )
    return "\n".join(blocks)


def retrieve_passages(
    knowledge_base: Any,
    query_text: str,
    acl_principals: tuple[str, ...] = (),
    filters: dict[str, str] | None = None,
    top_k: int = 10,
) -> list[RetrievedPassage]:
    """Run a governed A2 search through the KnowledgeBaseClientPort defensively."""
    query = RetrievalQuery(
        text=query_text,
        top_k=top_k,
        acl_principals=tuple(acl_principals),
        filters=dict(filters or {}),
    )
    passages = knowledge_base.search(query)
    return list(passages or [])


def parse_structured(response: Any) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure (plain text,
    truncation, a fenced block) we fall back to extracting the first balanced JSON
    object, and finally to an empty dict so callers degrade gracefully rather than
    raising on a malformed model reply.
    """
    text = (getattr(response, "text", "") or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    snippet = _extract_json_object(text)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def citations_for_source_ids(
    used_source_ids: list[str],
    passages: list[RetrievedPassage],
) -> tuple[Citation, ...]:
    """Map model-returned ``used_source_ids`` back to retrieved passage Citations.

    Preserves the page-level provenance from retrieval (the model only returns ids,
    never pages). When a source_id was cited by multiple passages, each distinct
    (source_id, page) citation is kept once, in retrieval order. Unknown ids the model
    may have hallucinated are dropped : we only ever cite what we retrieved.
    """
    by_id: dict[str, list[Citation]] = {}
    for p in passages:
        by_id.setdefault(p.citation.source_id, []).append(p.citation)

    wanted = list(used_source_ids or [])
    # If the model returned nothing usable, fall back to all retrieved citations so an
    # artifact is never left provenance-less.
    selected_ids = [sid for sid in wanted if sid in by_id]
    if not selected_ids:
        selected_ids = list(by_id.keys())

    out: list[Citation] = []
    seen: set[tuple[str, int | None]] = set()
    for sid in selected_ids:
        for citation in by_id.get(sid, ()):
            key = (citation.source_id, citation.page)
            if key not in seen:
                seen.add(key)
                out.append(citation)
    return tuple(out)


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.HIGH,
    temperature: float = 0.2,
    max_output_tokens: int = 4096,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning model,
    ``gemini-3.5-flash``); thinking defaults to HIGH for grounded reasoning per SPEC.
    """
    return LlmRequest(
        messages=(LlmMessage(role="user", content=user_content),),
        system_instruction=system_instruction,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
    )


def maybe_record_usage(tracer: Any, response: Any) -> None:
    """Emit token usage to the tracer for FinOps, defensively (never fatal)."""
    try:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "") or ""
        if usage is not None and hasattr(tracer, "record_token_usage"):
            tracer.record_token_usage(usage, model)
    except Exception:  # noqa: BLE001 - metrics must never break a generation path
        return


def as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary model value into a list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []
