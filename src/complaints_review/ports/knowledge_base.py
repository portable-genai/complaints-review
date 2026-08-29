"""KnowledgeBaseClientPort — the governed RAG store for policy & regulatory guidance.

B6 does **not** build its own retrieval backend: policy and regulatory guidance used to
categorise a complaint and ground the draft response are retrieved from the shared
**A2 Enterprise Knowledge Base** (rule R3, governed RAG). The ``platform`` adapter is a
thin HTTP client to A2's ``/v1/search`` (env ``KNOWLEDGE_BASE_URL``); the on-prem placeholder
stub raises, and a direct GCP adapter (Agent Search) is available for standalone runs.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import RetrievalQuery, RetrievedPassage


@runtime_checkable
class KnowledgeBaseClientPort(Protocol):
    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Retrieve ranked, ACL-filtered passages for grounding the review.

        ACL contract (enforced by every adapter, fail-closed): a passage with no
        ``acl_tags`` is public; a tagged passage is returned only when
        ``query.acl_principals`` hold EVERY one of its tags (subset / all-of match). So a
        passage tagged ``tenant:<t>`` is visible only to a caller carrying that
        ``tenant:<t>`` principal, and an empty principal set sees only untagged passages.
        The verified tenant and entitlements are stamped into ``acl_principals``
        server-side, never taken from the request body.
        """
        ...
