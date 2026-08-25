"""MCP tool-catalog adapter (ToolCatalogPort, A3, rule R4).

Exposes the governed, least-privilege tools B6 makes available over **MCP** (Model
Context Protocol 2026-07-28). For a standalone deployment this adapter serves a static,
in-process catalog describing the three B6 skills; in the full platform the governed MCP
catalog is hosted by the A3 registry. The tool schemas here are the contract surface a
peer agent sees.

This adapter imports no Google Cloud SDK; it is a thin in-process catalog.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import ToolSpec

# MCP protocol revision this catalog conforms to. The stateless era: the initialize
# handshake this catalog once assumed was removed in this revision.
MCP_PROTOCOL_VERSION = "2026-07-28"

_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="review_complaint",
        description=(
            "Build a full cited complaint review: summary, categorisation, conduct flags "
            "and a draft response (always human-reviewed, never auto-sent)."
        ),
        input_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
    ),
    ToolSpec(
        name="categorise",
        description="Categorise a complaint with root cause, severity and conduct flags.",
        input_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
    ),
    ToolSpec(
        name="draft_response",
        description="Draft a regulator/customer response grounded in policy (a draft, not sent).",
        input_schema={
            "type": "object",
            "properties": {"file_id": {"type": "string"}},
            "required": ["file_id"],
        },
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
