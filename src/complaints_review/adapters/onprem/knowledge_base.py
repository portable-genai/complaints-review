"""On-prem placeholder for ``KnowledgeBaseClientPort`` : Google Distributed Cloud target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed/platform
profile this port binds to the A2 Enterprise KB client (or Agent Search); switching
``profile`` to ``onprem`` rebinds it here. The adapter constructs cleanly with **no
external dependencies** and structurally satisfies the same Protocol as the managed
adapter, so the contract tests prove interface parity. ``search`` deliberately raises
rather than returning empty results: an unimplemented governed-RAG backend must never
silently produce an ungrounded review, so porting on-premise *must* supply a real
retrieval backend. Filling this body in is the only change required.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import RetrievalQuery, RetrievedPassage

_MESSAGE = (
    "On-prem KnowledgeBaseClientPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremKnowledgeBaseAdapter:
    """Placeholder knowledge-base adapter for the on-prem (Google Distributed Cloud) profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        raise NotImplementedError(_MESSAGE)
