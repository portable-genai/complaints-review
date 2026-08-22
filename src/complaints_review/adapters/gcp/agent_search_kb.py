"""Agent Search knowledge-base adapter (KnowledgeBaseClientPort, standalone).

B6's governed RAG store for policy / regulatory guidance **is** the A2 Enterprise KB; the
``platform`` adapter delegates to A2 over HTTP. For a standalone run this adapter speaks
directly to **Agent Search** (Discovery Engine) on the Gemini Enterprise Agent Platform,
pinned to a **regional** endpoint in ``asia-southeast1`` so the policy corpus stays
in-country. ``search`` returns ranked passages with page-level :class:`Citation`
provenance.

All Google Cloud SDK imports are lazy so the on-prem / test profile imports this module
without ``google-cloud-discoveryengine`` installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.cloud import discoveryengine_v1

_SOURCE_TYPE_BY_VALUE: dict[str, SourceType] = {s.value: s for s in SourceType}


class AgentSearchKnowledgeBaseAdapter:
    """Direct Agent Search governed-RAG adapter (standalone fallback for A2)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg = settings.agent_search
        self._location = cfg.location
        self._data_store_id = cfg.data_store_id
        self._serving_config_id = cfg.serving_config
        self._endpoint = f"{self._location}-discoveryengine.googleapis.com"
        self._search_client: Any | None = None

    def _search(self) -> discoveryengine_v1.SearchServiceClient:
        if self._search_client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import discoveryengine_v1

            self._search_client = discoveryengine_v1.SearchServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint),
            )
        return self._search_client

    def _serving_config(self) -> str:
        return (
            f"projects/{self._settings.project_id}/locations/{self._location}"
            f"/collections/default_collection/dataStores/{self._data_store_id}"
            f"/servingConfigs/{self._serving_config_id}"
        )

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Return ranked policy/regulatory passages with page-level citations."""
        from google.cloud import discoveryengine_v1

        client = self._search()
        content_spec = discoveryengine_v1.SearchRequest.ContentSearchSpec(
            extractive_content_spec=(
                discoveryengine_v1.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_segment_count=max(query.top_k, 1),
                    return_extractive_segment_score=True,
                )
            ),
        )
        request = discoveryengine_v1.SearchRequest(
            serving_config=self._serving_config(),
            query=query.text,
            page_size=query.top_k,
            filter=self._acl_filter(query.acl_principals),
            content_search_spec=content_spec,
        )
        response = client.search(request=request)
        passages: list[RetrievedPassage] = []
        for result in response.results:
            passages.extend(self._result_to_passages(result))
        return passages

    @staticmethod
    def _acl_filter(principals: tuple[str, ...]) -> str:
        clauses = [f'acl_tags: ANY("{p}")' for p in principals if p]
        return " AND ".join(clauses)

    def _result_to_passages(self, result: Any) -> list[RetrievedPassage]:
        document = result.document
        struct = self._to_dict(getattr(document, "struct_data", None))
        derived = self._to_dict(getattr(document, "derived_struct_data", None))
        source_id = str(struct.get("source_id") or getattr(document, "id", "") or "unknown")
        title = str(struct.get("title") or source_id)
        url = str(struct.get("url") or "")
        source_type = _SOURCE_TYPE_BY_VALUE.get(
            str(struct.get("source_type") or "policy"), SourceType.POLICY
        )

        segments = derived.get("extractive_segments") or []
        if not segments:
            citation = Citation(
                source_id=source_id,
                source_type=source_type,
                title=title,
                url=url,
                page=None,
            )
            return [RetrievedPassage(text="", citation=citation, score=0.0)]

        passages: list[RetrievedPassage] = []
        for segment in segments:
            seg = self._to_dict(segment)
            text = str(seg.get("content") or "")
            page = self._parse_page(seg.get("pageIdentifier"))
            score = self._parse_score(seg.get("relevanceScore"))
            citation = Citation(
                source_id=source_id,
                source_type=source_type,
                title=title,
                url=url,
                page=page,
                snippet=text[:280],
                score=score,
            )
            passages.append(RetrievedPassage(text=text, citation=citation, score=score or 0.0))
        return passages

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return dict(value)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _parse_page(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_score(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
