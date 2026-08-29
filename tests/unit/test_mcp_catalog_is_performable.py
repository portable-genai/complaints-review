"""The declared MCP tools must ask for what this tree can actually act on.

The catalog is the contract surface a peer agent reads. Until 2026-08-29 every tool in it
declared exactly one input, ``file_id``, and required it: a caller was told to name a
complaint and nothing else. Nothing here can honour that. ``ComplaintReviewService.review``
takes a whole :class:`ComplaintFile`, no complaint store exists anywhere under
``domain/`` to resolve an id against, and both real call paths already carry the complaint
in the request (``api/app.py``'s ``ReviewRequest.file``, and the ADK callables in
``agent/tools.py``, which take ``file_id`` PLUS ``narrative`` and build the file from the
payload). The declaration promised a capability the system does not have, which is worse
than an absent declaration: it reads as reviewed.

These tests pin the fix from the side that can rot. The catalog is a literal, the callables
are the implementation, and the two are compared here rather than kept in step by hand.
``actor`` and ``settings`` are excluded by name and with a reason: ``actor`` is the verified
identity the server resolves and must never be client-asserted, and ``settings`` is
dependency injection that no caller passes.

What this file does NOT change is whether the catalog is served. That question is answered,
for a different reason, in ``test_tool_catalog_is_declared_and_deliberately_unserved.py``:
every tool names a complaint id, object-level authorization decides on that id, and the
principal an MCP stdio transport supplies is refused it. Carrying the narrative alongside
the id removes the missing lookup; it does not remove the access check.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from complaints_review.adapters.gcp.mcp_tool_catalog import McpToolCatalogAdapter
from complaints_review.agent.tools import TOOL_FUNCTIONS
from complaints_review.config import Settings

CONFIG_PATH = "config/settings.yaml"

#: Parameters the model never supplies, so they are absent from the declared schema.
#: ``actor`` is resolved server-side from the verified principal and accepting it from a
#: caller would be identity spoofing; ``settings`` is the DI seam the tests use.
_SERVER_OWNED = frozenset({"actor", "settings"})


@pytest.fixture
def catalog() -> McpToolCatalogAdapter:
    return McpToolCatalogAdapter(Settings.load(CONFIG_PATH))


def _callable_inputs(fn: Any) -> tuple[set[str], set[str]]:
    """(all model-facing parameter names, the subset with no default)."""
    parameters = [
        p for name, p in inspect.signature(fn).parameters.items() if name not in _SERVER_OWNED
    ]
    every = {p.name for p in parameters}
    required = {p.name for p in parameters if p.default is inspect.Parameter.empty}
    return every, required


def test_the_catalog_declares_exactly_the_callables_that_exist(
    catalog: McpToolCatalogAdapter,
) -> None:
    declared = {spec.name for spec in catalog.list_tools()}
    implemented = {fn.__name__ for fn in TOOL_FUNCTIONS}
    assert declared == implemented


@pytest.mark.parametrize("fn", TOOL_FUNCTIONS, ids=lambda fn: fn.__name__)
def test_each_declared_schema_matches_the_callable_it_names(
    catalog: McpToolCatalogAdapter, fn: Any
) -> None:
    spec = catalog.get_tool(fn.__name__)
    assert spec is not None, f"{fn.__name__} is implemented but not declared"

    every, required = _callable_inputs(fn)
    assert set(spec.input_schema["properties"]) == every, (
        f"{fn.__name__}'s declared inputs and its signature disagree; a peer agent would send "
        "a payload the callable cannot accept, or omit one it needs"
    )
    assert set(spec.input_schema["required"]) == required


def test_no_tool_asks_only_for_an_id_it_cannot_resolve(catalog: McpToolCatalogAdapter) -> None:
    """The defect itself, stated as an assertion.

    An id-only tool is unperformable here: there is no store to look the complaint up in, so
    the narrative has to arrive with the request. This fails on the exact pre-2026-08-29
    shape, ``{"properties": {"file_id": ...}, "required": ["file_id"]}``.
    """
    for spec in catalog.list_tools():
        assert "narrative" in spec.input_schema["required"], (
            f"{spec.name} does not require the complaint text, so it can only be satisfied by "
            "resolving file_id against a store this tree does not have"
        )


def test_the_declared_payload_actually_builds_a_complaint_file() -> None:
    """The end of the chain: the declared fields are the ones the domain object needs.

    A schema can agree with a signature and still describe nothing usable, so this drives the
    real constructor the tools use rather than trusting the names.
    """
    from complaints_review.agent.tools import _file

    file = _file(
        file_id="cmp-0001",
        narrative="The branch sold me a product I did not understand.",
        product="structured investment product",
        channel="branch",
        received_date="2026-08-01",
        customer_ref="CUST-FAKE-1",
    )

    assert file.id == "cmp-0001"
    assert file.narrative.startswith("The branch sold me")
    assert file.channel.value == "branch"


def test_no_declared_schema_leaks_a_server_owned_parameter(
    catalog: McpToolCatalogAdapter,
) -> None:
    """``actor`` must not be askable. A client-asserted actor is a forged audit subject."""
    for spec in catalog.list_tools():
        assert not (_SERVER_OWNED & set(spec.input_schema["properties"])), spec.name
