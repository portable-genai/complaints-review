"""Remote-platform knowledge-base adapter — thin HTTP client to A2.

B6's governed RAG store for policy / regulatory guidance is the shared **A2 Enterprise
Knowledge Base** (``enterprise-knowledge-base``). This adapter implements
:class:`KnowledgeBaseClientPort` by POSTing to A2's ``/v1/search`` endpoint (SPEC §6, A2
contract), so policy and regulatory passages used to categorise a complaint and ground a
draft response are retrieved via A2 governed search (rule R3) rather than B6 building its
own backend.

The base URL is read from ``HRZ_KB_URL`` with a localhost default.
"""

from __future__ import annotations

import httpx

from ...domain.errors import ComplaintsError
from ...domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8082"
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)

_SOURCE_TYPE_BY_VALUE = {s.value: s for s in SourceType}


class RemoteKnowledgeBaseError(ComplaintsError):
    """Raised when the A2 knowledge-base service returns a non-2xx response."""


class RemoteKnowledgeBaseAdapter:
    """HTTP client for the A2 ``enterprise-knowledge-base`` service."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("HRZ_KB_URL", _DEFAULT_URL), service="knowledge base"
        )

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Retrieve ACL-filtered policy/regulatory passages from A2 for grounding."""
        payload = {
            "query": query.text,
            "top_k": query.top_k,
            "acl_principals": list(query.acl_principals),
            "filters": dict(query.filters),
        }
        url = f"{self._base_url}/v1/search"
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:
            raise RemoteKnowledgeBaseError(f"A2 request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteKnowledgeBaseError(
                f"A2 {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json()
        body = body if isinstance(body, dict) else {}
        return [self._to_passage(item) for item in (body.get("passages") or ())]

    @staticmethod
    def _to_passage(item: dict) -> RetrievedPassage:
        raw_citation = item.get("citation") or {}
        source_type = _SOURCE_TYPE_BY_VALUE.get(
            str(raw_citation.get("source_type") or "policy"), SourceType.POLICY
        )
        citation = Citation(
            source_id=str(raw_citation.get("source_id", "")),
            source_type=source_type,
            title=str(raw_citation.get("title", "")),
            url=str(raw_citation.get("url", "")),
            page=raw_citation.get("page"),
            snippet=str(raw_citation.get("snippet", "")),
            score=raw_citation.get("score"),
        )
        return RetrievedPassage(
            text=str(item.get("text", "")),
            citation=citation,
            score=float(item.get("score", 0.0) or 0.0),
        )
