"""Server-side complaint entitlements (object-level authorization for retrieval).

Entitlement to a complaint file is decided from the VERIFIED principal, never from a
client-supplied id: a role member (or explicit ``complaint:<id>`` grant) is admitted, and
the returned scope stamps ``tenant:<t>`` server-side so a shared governed corpus stays
tenant-partitioned. An unentitled principal is refused (maps to HTTP 403).
"""

from __future__ import annotations

import pytest

from complaints_review.domain.entitlements import (
    complaint_acl,
    complaint_acl_ok,
    complaint_scope,
    may_access_complaint,
)
from complaints_review.domain.errors import AccessDeniedError
from complaints_review.domain.identity import Principal


def _analyst(tenant: str = "demo-bank") -> Principal:
    return Principal(
        subject="demo.analyst@bank.example",
        principals=("group:complaints-analyst", "group:conduct"),
        tenant=tenant,
    )


# --------------------------------------------------------------------------- #
# may_access_complaint : role membership or an explicit grant admits; else no.
# --------------------------------------------------------------------------- #
def test_role_member_may_access() -> None:
    assert may_access_complaint(_analyst(), "CMP-2026-0001") is True


def test_explicit_grant_may_access_without_a_role() -> None:
    granted = Principal(subject="ext@bank.example", principals=("complaint:CMP-2026-0001",))
    assert may_access_complaint(granted, "CMP-2026-0001") is True
    # ...but only for the granted file, not a different one.
    assert may_access_complaint(granted, "CMP-2026-9999") is False


def test_principal_without_role_or_grant_is_denied() -> None:
    stranger = Principal(subject="stranger@bank.example", principals=("group:unrelated",))
    assert may_access_complaint(stranger, "CMP-2026-0001") is False


# --------------------------------------------------------------------------- #
# complaint_scope : server-derived retrieval principals (raises when unentitled).
# --------------------------------------------------------------------------- #
def test_scope_stamps_tenant_and_complaint_server_side() -> None:
    scope = complaint_scope(_analyst(), "CMP-2026-0001")
    assert "tenant:demo-bank" in scope  # tenant partition stamped from the verified principal
    assert "complaint:CMP-2026-0001" in scope
    assert "group:complaints-analyst" in scope  # the principal's own entitlements carry through


def test_scope_without_tenant_omits_the_tenant_tag() -> None:
    scope = complaint_scope(_analyst(tenant=""), "CMP-2026-0001")
    assert not any(s.startswith("tenant:") for s in scope)
    assert "complaint:CMP-2026-0001" in scope


def test_scope_raises_for_unentitled_principal() -> None:
    stranger = Principal(subject="stranger@bank.example", principals=("group:unrelated",))
    with pytest.raises(AccessDeniedError):
        complaint_scope(stranger, "CMP-2026-0001")


# --------------------------------------------------------------------------- #
# complaint_acl / complaint_acl_ok : the tag set + fail-closed subset match.
# --------------------------------------------------------------------------- #
def test_complaint_acl_tags() -> None:
    assert complaint_acl("CMP-1", "demo-bank") == ("complaint:CMP-1", "tenant:demo-bank")
    assert complaint_acl("CMP-1", "") == ("complaint:CMP-1",)


def test_complaint_acl_ok_is_fail_closed_subset() -> None:
    tags_held = ("complaint:CMP-1", "tenant:demo-bank", "group:x")
    assert complaint_acl_ok("CMP-1", "demo-bank", tags_held) is True
    # Wrong tenant, even with the right complaint id, is denied (no boundary crossing).
    assert complaint_acl_ok("CMP-1", "other-bank", tags_held) is False
