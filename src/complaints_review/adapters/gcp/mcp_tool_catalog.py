"""MCP tool-catalog adapter (ToolCatalogPort, A3, rule R4).

Exposes the governed, least-privilege tools B6 makes available over **MCP** (Model
Context Protocol 2026-07-28). For a standalone deployment this adapter serves a static,
in-process catalog describing the three B6 skills; in the full platform the governed MCP
catalog is hosted by the A3 registry. The tool schemas here are the contract surface a
peer agent sees.

Each schema CARRIES the complaint, and names it. Until 2026-08-29 every tool declared
``file_id`` alone, which promised a lookup this tree cannot perform: ``ComplaintReviewService``
takes a whole :class:`ComplaintFile`, no complaint store exists to resolve an id against, and
both real call paths (``api/app.py``'s ``ReviewRequest.file`` and the ADK callables in
``agent/tools.py``) receive the narrative in the request. A caller who sent only an id would
have been answered by nothing. The schemas now mirror ``agent.tools.TOOL_FUNCTIONS`` exactly,
minus the two parameters no caller supplies: ``actor`` is the VERIFIED identity the server
resolves, and ``settings`` is dependency injection. That correspondence is pinned by
``tests/unit/test_mcp_catalog_is_performable.py``, so the two cannot drift apart again.

``file_id`` stays REQUIRED and top-level, because it is what object-level authorization decides
on: ``entitlements.complaint_scope(principal, file.id)`` gates every artifact route. Carrying
the narrative alongside it removes the missing lookup, not the access check, so the reasoning in
``tests/unit/test_tool_catalog_is_declared_and_deliberately_unserved.py`` is unchanged.

This adapter imports no Google Cloud SDK; it is a thin in-process catalog.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

# MCP protocol revision this catalog conforms to. The stateless era: the initialize
# handshake this catalog once assumed was removed in this revision.
MCP_PROTOCOL_VERSION = "2026-07-28"

#: The complaint every tool operates on, spelled once. ``file_id`` and ``narrative`` are the
#: two the callables require positionally; the rest carry defaults in ``agent/tools.py`` and are
#: therefore optional here too. Written once and shared, because three copies of a schema are
#: three chances for one of them to drift.
_COMPLAINT_PROPERTIES: dict[str, dict[str, str]] = {
    "file_id": {
        "type": "string",
        "description": (
            "The complaint file identifier. Object-level authorization is decided on this "
            "value, server-side, from the verified principal."
        ),
    },
    "narrative": {
        "type": "string",
        "description": (
            "The customer's account of the complaint, in free text. Redacted at the boundary "
            "before any model, index or audit call."
        ),
    },
    "product": {"type": "string", "description": "The product the complaint is about."},
    "channel": {
        "type": "string",
        "description": (
            "The channel the complaint arrived through. An unrecognised value is recorded as "
            "'other' rather than refused."
        ),
    },
    "received_date": {
        "type": "string",
        "description": "ISO date the complaint was received; it starts the deadline clock.",
    },
    "customer_ref": {"type": "string", "description": "Pseudonymous customer reference."},
}

#: The two the service cannot work without: an id to authorize against and the text to review.
_REQUIRED_PROPERTIES: tuple[str, ...] = ("file_id", "narrative")


def _complaint_schema() -> dict:
    """A fresh input schema per tool, so no ToolSpec can mutate another's."""
    return {
        "type": "object",
        "properties": {name: dict(spec) for name, spec in _COMPLAINT_PROPERTIES.items()},
        "required": list(_REQUIRED_PROPERTIES),
    }


_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="review_complaint",
        description=(
            "Build a full cited complaint review: summary, categorisation, conduct flags "
            "and a draft response (always human-reviewed, never auto-sent)."
        ),
        input_schema=_complaint_schema(),
    ),
    ToolSpec(
        name="categorise",
        description="Categorise a complaint with root cause, severity and conduct flags.",
        input_schema=_complaint_schema(),
    ),
    ToolSpec(
        name="draft_response",
        description="Draft a regulator/customer response grounded in policy (a draft, not sent).",
        input_schema=_complaint_schema(),
    ),
)


class McpToolCatalogAdapter:
    """Static governed MCP tool catalog for the standalone profile."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tools = {tool.name: tool for tool in _TOOLS}

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)
