"""Why this tree declares a governed tool catalog and deliberately does not serve it.

Fourteen trees in the fleet serve the catalog they declare, over MCP 2026-07-28 on stdio. This
one does not, and the reason has to be executable rather than asserted, because "we decided not
to" is exactly the kind of claim that rots into "nobody got round to it".

**The reason is identity, and it is not a gap in the plumbing.** Every tool in this catalog
NAMES the complaint it acts on, with a required ``file_id``, and acting on a named complaint is
gated on entitlement to it. ``entitlements.complaint_scope`` decides that server-side from the
VERIFIED principal: a caller
holds either an explicit ``complaint:<id>`` grant or a complaint-access role, and holds neither
by default. MCP stdio verifies no end user at all. The fleet's serving trees supply an EMPTY
principal there and rely on entitlement FILTERING, which degrades safely: an empty principal
sees untagged public data and nothing else. This tree's authorization is not filtering. It is an
object-level gate that RAISES, so the same empty principal is refused every complaint.

That leaves three options and only one honest one. Serving with an empty principal would bind
cleanly and refuse every call, which is a dead surface wearing a green tick. Manufacturing a
principal to make the calls succeed would forge the entitlement the gate exists to check.
Leaving it declared and unserved is the truthful state, and these guards are what stop that
state from being mistaken for an oversight.

The first guard PROVES the refusal by executing it. The second stops an MCP server appearing
here without someone reckoning with the first.
"""

from __future__ import annotations

import pathlib

import pytest

from complaints_review.adapters.gcp.mcp_tool_catalog import McpToolCatalogAdapter
from complaints_review.config import Settings
from complaints_review.domain.entitlements import complaint_scope
from complaints_review.domain.errors import AccessDeniedError
from complaints_review.domain.identity import Principal

CONFIG_PATH = "config/settings.yaml"

#: The identity MCP stdio would supply: a service caller, verified as no end user at all.
#: Named rather than inlined, because the whole finding is about what this value cannot do.
_MCP_STDIO_PRINCIPAL = Principal(subject="svc:unattributed", principals=(), tenant="")


@pytest.fixture
def catalog() -> McpToolCatalogAdapter:
    return McpToolCatalogAdapter(Settings.load(CONFIG_PATH))


def test_every_declared_tool_is_keyed_on_an_object_id(catalog: McpToolCatalogAdapter) -> None:
    """The premise of everything below: these tools name the complaint they act on.

    The tools carry the complaint text too, because nothing here can resolve an id against a
    store (see ``test_mcp_catalog_is_performable.py``). The ID is what matters HERE: it is the
    object ``entitlements.complaint_scope`` decides on, and a tool that named no complaint would
    have no object to gate. Asserted rather than assumed, so that dropping the id makes this
    file's reasoning stop applying loudly.
    """
    declared = catalog.list_tools()

    assert declared, "an empty catalog would make every assertion in this file vacuous"
    for spec in declared:
        assert "file_id" in spec.input_schema["required"], (
            f"{spec.name} no longer requires a file_id, so it names no object for the "
            "entitlement gate to decide on, and the identity argument in this module's "
            "docstring needs revisiting"
        )


def test_the_identity_mcp_stdio_would_supply_is_refused_every_declared_tool(
    catalog: McpToolCatalogAdapter,
) -> None:
    """The reason this tree does not serve, executed rather than asserted.

    Proved by running the real authorization for each declared tool with the exact principal an
    MCP stdio transport produces. Every one refuses. A served catalog would therefore be a
    catalog of tools that cannot succeed.
    """
    declared = catalog.list_tools()
    assert declared, "an empty catalog would prove nothing here"

    for spec in declared:
        with pytest.raises(AccessDeniedError):
            complaint_scope(_MCP_STDIO_PRINCIPAL, f"complaint-for-{spec.name}")


def test_an_entitled_principal_is_admitted_so_the_refusal_above_is_about_identity(
    catalog: McpToolCatalogAdapter,
) -> None:
    """The other half, without which the guard above proves only that something always raises.

    A principal holding the explicit grant is admitted for the same id. So the refusal is the
    entitlement gate doing its job, not a broken call.
    """
    file_id = "complaint-0001"
    entitled = Principal(
        subject="reviewer@example.invalid",
        principals=(f"complaint:{file_id}",),
        tenant="tenant-a",
    )

    scope = complaint_scope(entitled, file_id)

    assert f"complaint:{file_id}" in scope
    assert "tenant:tenant-a" in scope


def test_this_tree_ships_no_mcp_server() -> None:
    """An MCP server must not appear here until the refusal above has an answer.

    Not a style rule. Adding one means either serving tools that always refuse, or supplying a
    principal nobody verified, and both are worse than the declared-and-unserved state this file
    documents. Whoever adds the server deletes this guard deliberately and says which it is.
    """
    package = pathlib.Path(__file__).resolve().parents[2] / "src" / "complaints_review"

    assert not (package / "mcp").exists(), (
        "an mcp/ package appeared: every declared tool is refused the identity MCP stdio "
        "supplies, so serving this catalog needs a reviewed answer to that first"
    )
