"""Unit tests for the IdentityPort adapters (server-side, verified identity).

The local persona adapter is the offline (no IdP/AD/LDAP) identity source used for demos
and tests; the on-prem adapter is a fail-fast placeholder. These prove the identity seam
that replaces the old client-asserted ``actor``.
"""

from __future__ import annotations

import pytest

from complaints_review.adapters.local.identity import LocalPersonaIdentityAdapter
from complaints_review.adapters.onprem.identity import OnPremIdentityAdapter
from complaints_review.config import Settings
from complaints_review.domain.identity import IdentityError, Principal, RequestContext

_SETTINGS = Settings(profile="local")


def _adapter() -> LocalPersonaIdentityAdapter:
    return LocalPersonaIdentityAdapter(_SETTINGS)


def test_default_persona_when_no_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={}))
    assert principal.subject == "demo.analyst@bank.example"
    assert principal.principals  # non-empty entitlements
    assert principal.tenant == "demo-bank"
    assert principal.actor == principal.subject  # audit actor is the verified subject


def test_persona_selected_by_header() -> None:
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "auditor"}))
    assert principal.subject == "demo.auditor@bank.example"
    assert principal.principals == ("group:audit",)


def test_persona_header_is_case_insensitive() -> None:
    # RequestContext lower-cases lookups, so a host that sends X-Dev-Persona still resolves.
    principal = _adapter().resolve(RequestContext(headers={"x-dev-persona": "other-tenant"}))
    assert principal.tenant == "other-bank"


def test_unknown_persona_raises() -> None:
    with pytest.raises(IdentityError):
        _adapter().resolve(RequestContext(headers={"x-dev-persona": "does-not-exist"}))


def test_personas_listing_for_picker() -> None:
    ids = {p["id"] for p in _adapter().personas()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_cross_tenant_persona_is_seeded() -> None:
    # A cross-tenant persona keeps per-tenant authorization demoable fully offline.
    tenants = {p["tenant"] for p in _adapter().personas()}
    assert {"demo-bank", "other-bank"} <= tenants


def test_onprem_identity_fails_fast() -> None:
    adapter = OnPremIdentityAdapter(_SETTINGS)
    with pytest.raises(NotImplementedError):
        adapter.resolve(RequestContext(headers={}))


# --------------------------------------------------------------------------- #
# Principal.entitlement_principals : client ids may only NARROW, never widen.
# --------------------------------------------------------------------------- #
def test_entitlement_principals_empty_request_uses_full_entitlement() -> None:
    p = Principal(subject="a@b", principals=("group:complaints-analyst", "group:conduct"))
    assert p.entitlement_principals() == ("group:complaints-analyst", "group:conduct")


def test_entitlement_principals_narrows_to_a_held_subset() -> None:
    p = Principal(subject="a@b", principals=("group:complaints-analyst", "group:conduct"))
    assert p.entitlement_principals(("group:conduct",)) == ("group:conduct",)


def test_entitlement_principals_drops_foreign_ids_never_widens() -> None:
    # A client asserting a privileged group it does not hold gains nothing (fail-closed).
    p = Principal(subject="a@b", principals=("group:complaints-analyst",))
    assert p.entitlement_principals(("group:audit",)) == ()
