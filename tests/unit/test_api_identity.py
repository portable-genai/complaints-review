"""API-boundary tests for server-verified identity (the client-asserted actor is gone).

These drive the FastAPI app through a TestClient with an in-memory container injected via
``deps.get_container`` (which is ``lru_cache``d, so we monkeypatch it rather than mutate
the environment). They prove:

* an unknown ``X-Dev-Persona`` is a hard 401 (the identity seam fails closed);
* with no persona header the DEFAULT persona's verified subject is the audit actor;
* a selected persona's verified subject becomes the audit actor;
* the verified user's entitlement principals reach the governed KB query (per-user authZ),
  sharing ONE knowledge-base instance between the review service and the assertion.
"""

from __future__ import annotations

from functools import cached_property
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import (
    RecordingAudit,
    RecordingExtraction,
    RecordingGuardrail,
    RecordingKnowledgeBase,
    RecordingLLM,
    RecordingRedaction,
    RecordingTracer,
)

from complaints_review.adapters.local.identity import LocalPersonaIdentityAdapter
from complaints_review.adapters.local.review_router import LocalReviewRouter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.identity import Principal, RequestContext
from complaints_review.domain.models import Citation, RetrievedPassage, SourceType

_SETTINGS = Settings(
    profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:")
)

_REVIEW_BODY: dict[str, Any] = {
    "file": {
        "id": "CMP-API-0001",
        "customer_ref": "CUST-FAKE-API",
        "product": "structured investment product",
        "channel": "branch",
        "received_date": "2026-06-01",
        "documents": [],
        "narrative": (
            "The branch sold me a structured investment product I did not understand and I "
            "am a recently bereaved and vulnerable customer who wants my money back."
        ),
    }
}


class _InMemoryContainer:
    """A minimal Container the API can pull ports from; one KB instance shared for asserts."""

    def __init__(self) -> None:
        self.settings = _SETTINGS
        self.extraction = RecordingExtraction(_SETTINGS)
        self.knowledge_base = RecordingKnowledgeBase(_SETTINGS)
        self.llm = RecordingLLM(_SETTINGS)
        self.guardrail = RecordingGuardrail(_SETTINGS)
        self.redaction = RecordingRedaction(_SETTINGS)
        self.tracer = RecordingTracer(_SETTINGS)
        self.audit = RecordingAudit(_SETTINGS)
        self.review_router = LocalReviewRouter(_SETTINGS)

    @cached_property
    def identity(self) -> LocalPersonaIdentityAdapter:
        return LocalPersonaIdentityAdapter(_SETTINGS)


@pytest.fixture
def container() -> _InMemoryContainer:
    return _InMemoryContainer()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, container: _InMemoryContainer) -> TestClient:
    from complaints_review.api import deps
    from complaints_review.api.app import app

    # deps.get_container is lru_cached: monkeypatch it to inject the in-memory container
    # rather than mutating the environment or clearing the cache.
    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=("127.0.0.1", 50000))


def test_an_unconsented_run_refuses_the_seeded_personas(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED before the three-state fix: an unset COMPLAINTS_PROFILE was read as "chose local".

    ``local`` binds the seeded-persona identity adapter, which authenticates nobody, so a
    process that merely lost an environment variable served the whole conduct-review API,
    complaint files and customer PII included, to any caller. It now answers 401, and the
    persona picker lists nothing.
    """
    from complaints_review.api import deps
    from complaints_review.api.app import app

    monkeypatch.delenv("COMPLAINTS_PROFILE", raising=False)
    monkeypatch.setenv("COMPLAINTS_LOCAL_DB", ":memory:")
    monkeypatch.setenv("COMPLAINTS_LOCAL_AUDIT", ":memory:")
    deps.get_container.cache_clear()
    try:
        api = TestClient(app, client=("127.0.0.1", 50000))
        refused = api.post("/v1/review", json=_REVIEW_BODY)
        listed = api.get("/v1/personas")
    finally:
        deps.get_container.cache_clear()

    assert refused.status_code == 401
    assert listed.json() == []


def test_unknown_persona_is_401(client: TestClient) -> None:
    response = client.post(
        "/v1/review", headers={"X-Dev-Persona": "does-not-exist"}, json=_REVIEW_BODY
    )
    assert response.status_code == 401


def test_default_persona_is_the_audit_actor(
    client: TestClient, container: _InMemoryContainer
) -> None:
    # No X-Dev-Persona header: the local adapter resolves the default (analyst) persona.
    response = client.post("/v1/review", json=_REVIEW_BODY)
    assert response.status_code == 200
    actors = {event.actor for event in container.audit.events}
    assert "demo.analyst@bank.example" in actors


def test_selected_persona_is_the_audit_actor(
    client: TestClient, container: _InMemoryContainer
) -> None:
    response = client.post("/v1/review", headers={"X-Dev-Persona": "auditor"}, json=_REVIEW_BODY)
    assert response.status_code == 200
    actors = {event.actor for event in container.audit.events}
    assert "demo.auditor@bank.example" in actors


def test_user_principals_reach_governed_retrieval(
    client: TestClient, container: _InMemoryContainer
) -> None:
    # The auditor persona carries group:audit; that entitlement principal must reach the
    # KB query alongside the request actor, proving per-user authZ scopes retrieval.
    response = client.post("/v1/review", headers={"X-Dev-Persona": "auditor"}, json=_REVIEW_BODY)
    assert response.status_code == 200
    assert container.knowledge_base.calls, "the KB was never queried"
    last = container.knowledge_base.calls[-1]
    assert "group:audit" in last.acl_principals
    # The request actor (the verified subject) is scoped into the ACL alongside the groups.
    assert "demo.auditor@bank.example" in last.acl_principals


def test_verified_tenant_is_stamped_into_retrieval_acl(
    client: TestClient, container: _InMemoryContainer
) -> None:
    # The SERVER-VERIFIED tenant (never the request body) is threaded into retrieval as a
    # ``tenant:<t>`` principal so the data path is partitioned by tenant, not just groups.
    response = client.post("/v1/review", json=_REVIEW_BODY)  # default = demo-bank analyst
    assert response.status_code == 200
    last = container.knowledge_base.calls[-1]
    assert "tenant:demo-bank" in last.acl_principals


# The distinctive tenant-tagged passage seeded for the cross-tenant isolation test. Its
# text overlaps the composed retrieval query so FTS surfaces it before the ACL filter runs.
_TENANT_TAGGED_ID = "demo-bank-internal-playbook"
_TENANT_TAGGED = RetrievedPassage(
    text=(
        "Demo-bank internal complaint-handling remediation playbook for vulnerable "
        "customers mis-sold a structured investment product."
    ),
    citation=Citation(
        source_id=_TENANT_TAGGED_ID,
        source_type=SourceType.POLICY,
        title="Demo-Bank Internal Remediation Playbook (FICTIONAL)",
        url="https://example.test/demo-bank-internal",
        page=1,
        snippet="internal remediation playbook",
        score=0.99,
    ),
    score=0.99,
    acl_tags=("tenant:demo-bank",),
)


def _retrieved_ids(container: _InMemoryContainer) -> set[str]:
    return {p.citation.source_id for results in container.knowledge_base.results for p in results}


def test_cross_tenant_tagged_passage_is_isolated(
    client: TestClient, container: _InMemoryContainer
) -> None:
    """A tenant-tagged passage reaches its own tenant but NOT a cross-tenant caller.

    Both personas are entitled by role (so both get 200), so the ONLY thing keeping the
    ``tenant:demo-bank`` passage out of the ``other-bank`` analyst's retrieval is the
    server-verified tenant partition + the fail-closed subset ACL filter. Against the old
    no-op search (which ignored ``acl_principals``) the cross-tenant assertion fails.
    """
    container.knowledge_base.add([_TENANT_TAGGED])

    # In-tenant demo-bank analyst (default persona): the tenant-tagged passage is retrieved.
    r_in = client.post("/v1/review", json=_REVIEW_BODY)
    assert r_in.status_code == 200
    assert _TENANT_TAGGED_ID in _retrieved_ids(container), (
        "the in-tenant caller must retrieve its own tenant-tagged evidence"
    )

    # Cross-tenant other-bank analyst: same role, different tenant -> fail-closed denial.
    container.knowledge_base.results.clear()
    r_out = client.post("/v1/review", headers={"X-Dev-Persona": "other-tenant"}, json=_REVIEW_BODY)
    assert r_out.status_code == 200
    assert _TENANT_TAGGED_ID not in _retrieved_ids(container), (
        "cross-tenant caller must NOT retrieve another tenant's tagged evidence"
    )


class _RolelessIdentity:
    """An IdentityPort stub resolving a verified principal with no complaint-access role."""

    def resolve(self, ctx: RequestContext) -> Principal:
        return Principal(
            subject="stranger@bank.example",
            principals=("group:unrelated",),
            tenant="demo-bank",
            source="stub",
        )


def test_unentitled_principal_is_403(client: TestClient, container: _InMemoryContainer) -> None:
    # A verified principal holding no complaint-access role (and no explicit grant) is
    # refused server-side: the entitlement gate raises AccessDeniedError -> HTTP 403.
    container.__dict__["identity"] = _RolelessIdentity()  # shadow the cached_property
    response = client.post("/v1/review", json=_REVIEW_BODY)
    assert response.status_code == 403
