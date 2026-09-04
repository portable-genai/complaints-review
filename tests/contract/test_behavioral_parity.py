"""Behavioral parity: the same request through every implementation of a port.

The structural contract suite (``test_port_parity``) proves every adapter *satisfies*
its Protocol. This suite proves the stronger claim behind the no-lock-in promise
(P-02): for one canonical request, every SDK-free implementation of a port behaves
identically at the boundary, so switching ``COMPLAINTS_PROFILE`` swaps the whole stack
without changing what the domain sees.

complaints-review ships REAL ``platform`` HTTP clients (thin horizontal-platform delegates)
alongside the ``local`` in-process adapters, so this suite covers three representative ports two
ways:

* **redaction** (real ``platform`` delegate): the same PII text is put through both, and
  the httpx client (mocked with respx at the documented A1 ``/v1/redact`` contract) is
  required to yield the IDENTICAL :class:`RedactionResult` the local regex adapter did,
  with the customer identifiers gone at both boundaries;
* **knowledge_base** (real ``platform`` delegate): the same query returns the SAME
  first-class :class:`RetrievedPassage` objects from the local FTS5 index and from the A2
  ``/v1/search`` client, and a fresh ``local`` index rebuilt from the same seed returns
  identical passages (determinism, the index is a derived asset);
* **llm** (NO platform sibling, deterministic local stub): the same request re-run yields
  a byte-identical response (determinism across reruns).

For every port ``onprem`` is the migration placeholder: it fails fast with
``NotImplementedError`` rather than returning a silent wrong answer.

Plus the end-to-end proof: the full ``ComplaintReviewService.review`` pipeline runs under
``local`` and fails fast under ``onprem`` with **zero domain edits**, only a profile line.

Runs fully offline (``COMPLAINTS_PROFILE=local pytest``): the horizontal-platform
endpoints are mocked with respx and never actually served. All data here is obviously
fictional.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
import respx

from complaints_review.config import Container, LocalSettings, Settings, instantiate
from complaints_review.domain.models import (
    Channel,
    ComplaintFile,
    LlmMessage,
    LlmRequest,
    RedactionResult,
    RetrievalQuery,
)
from complaints_review.domain.serialization import to_jsonable

CONFIG_PATH = "config/settings.yaml"

# The platform clients' localhost defaults (SPEC contract): mocked, never actually served.
# These MUST match the env-var defaults hard-coded in the remote_* adapters.
GUARDRAIL_GATEWAY = "http://localhost:8080"  # remote_redaction / remote_guardrail
KNOWLEDGE_BASE = "http://localhost:8082"  # remote_knowledge_base (KNOWLEDGE_BASE_URL)

# Fictional complaint PII: a Singapore NRIC and an email the redactor must mask.
PII_TEXT = (
    "Complainant Priya Kumar (FICTIONAL), NRIC S1234567A, email priya.kumar@example.test, "
    "disputes the suitability of a structured investment product sold at the branch."
)


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    return replace(
        base, profile=profile, local=LocalSettings(db_path=":memory:", audit_path=":memory:")
    )


def _adapter(port: str, profile: str):
    settings = _settings(profile)
    return instantiate(settings.adapters[port][profile], settings)


# --------------------------------------------------------------------------- #
# PIIRedactionPort — real platform delegate: same request, identical result,
# customer PII gone at every implementation's boundary.
# --------------------------------------------------------------------------- #
def test_redaction_parity_local_equals_platform():
    local_result = _adapter("redaction", "local").redact(PII_TEXT)

    with respx.mock:
        # The A1 gateway is DLP-backed; serve its documented /v1/redact answer for the same
        # request. Echoing the local result proves the httpx client parses the A1 contract
        # back into the IDENTICAL domain object the offline regex adapter produced.
        respx.post(f"{GUARDRAIL_GATEWAY}/v1/redact").respond(200, json=to_jsonable(local_result))
        platform_result = _adapter("redaction", "platform").redact(PII_TEXT)

    assert platform_result == local_result, "platform redaction diverged from local at the boundary"

    for impl, result in (("local", local_result), ("platform", platform_result)):
        assert isinstance(result, RedactionResult), impl
        assert "S1234567A" not in result.text, f"{impl} leaked the NRIC"
        assert "priya.kumar@example.test" not in result.text, f"{impl} leaked the email"
        info_types = {finding.info_type for finding in result.findings}
        assert {"SG_NRIC_FIN", "EMAIL_ADDRESS"} <= info_types, f"{impl}: {info_types}"

    # onprem is the fail-fast migration placeholder: raise, never leak unredacted PII.
    with pytest.raises(NotImplementedError):
        _adapter("redaction", "onprem").redact(PII_TEXT)


# --------------------------------------------------------------------------- #
# KnowledgeBaseClientPort — real platform delegate: identical passages (as
# domain objects) either way, plus local determinism across a re-run.
# --------------------------------------------------------------------------- #
def test_knowledge_base_parity_local_equals_platform_and_is_deterministic():
    query = RetrievalQuery(
        text="complaint handling policy final response window fair dealing suitability",
        top_k=5,
    )

    local_kb = _adapter("knowledge_base", "local")  # self-seeds the built-in policy corpus
    local_passages = local_kb.search(query)
    assert local_passages, "local FTS5 search found nothing in the seeded policy corpus"
    assert all(p.citation.page is not None for p in local_passages), "page-level citation required"

    with respx.mock:
        # A2 serves the same passages for the same query (SPEC /v1/search shape).
        respx.post(f"{KNOWLEDGE_BASE}/v1/search").respond(
            200, json={"passages": [to_jsonable(p) for p in local_passages]}
        )
        platform_passages = _adapter("knowledge_base", "platform").search(query)

    # Not merely the same shape: the same first-class domain objects either way.
    assert platform_passages == local_passages, "platform KB diverged from local at the boundary"

    # A fresh local index rebuilt from the same seed yields identical passages: the index is
    # a derived asset, so retrieval is deterministic across reruns for the same query.
    rerun_passages = _adapter("knowledge_base", "local").search(query)
    assert rerun_passages == local_passages, "local KB retrieval not deterministic across reruns"

    # onprem is the fail-fast migration placeholder: raise rather than answer ungrounded.
    with pytest.raises(NotImplementedError):
        _adapter("knowledge_base", "onprem").search(query)


# --------------------------------------------------------------------------- #
# LLMPort — no platform sibling (deterministic local stub): the same request
# re-run is byte-identical; onprem fails fast.
# --------------------------------------------------------------------------- #
def test_llm_parity_local_is_deterministic_and_onprem_fails_fast():
    request = LlmRequest(
        messages=(
            LlmMessage(
                role="user",
                content=(
                    "[complaints-handling-policy p.3] [mas-fair-dealing-guidelines p.12] "
                    "Summarise the complaint and cite the grounding sources."
                ),
            ),
        ),
        system_instruction="You summarise complaints and cite sources.",
        response_schema={"type": "object", "properties": {"issue": {"type": "string"}}},
    )

    first = _adapter("llm", "local").generate(request)
    second = _adapter("llm", "local").generate(request)
    # The offline LLM is schema-driven and deterministic: no model, no network, same bytes.
    assert first == second, "local LLM was not deterministic across reruns for the same request"
    assert first.text, "local LLM returned an empty completion"

    with pytest.raises(NotImplementedError):
        _adapter("llm", "onprem").generate(request)
    with pytest.raises(NotImplementedError):
        _adapter("llm", "onprem").classify("route this", ["a", "b"])


# --------------------------------------------------------------------------- #
# End to end: one profile line swaps the whole stack, the domain is untouched.
# --------------------------------------------------------------------------- #
def _fictional_complaint() -> ComplaintFile:
    return ComplaintFile(
        id="CMP-PARITY-0001",
        customer_ref="CUST-FAKE-777",
        product="structured investment product",
        channel=Channel.BRANCH,
        received_date="2026-06-01",
        documents=("doc-parity-1",),
        narrative=(
            "Complainant disputes the suitability of a structured investment product sold "
            "at the branch and asks for the fees charged to be reviewed."
        ),
    )


def test_full_pipeline_local_works_onprem_fails_fast():
    from complaints_review.api.deps import build_review_service

    complaint = _fictional_complaint()

    # local: the whole offline stack runs and produces a grounded, human-review artifact.
    local_review = build_review_service(Container(_settings("local"))).review(
        complaint, actor="parity@test"
    )
    assert local_review.requires_human_review is True
    all_citations = (
        list(local_review.summary.citations)
        + list(local_review.categorization.citations)
        + [c for flag in local_review.conduct_flags for c in flag.citations]
        + (list(local_review.draft_response.citations) if local_review.draft_response else [])
    )
    assert all_citations, "offline run must still be grounded and cited"

    # onprem: the SAME call, only the profile changed, fails fast (redaction placeholder
    # raises first) rather than emitting an unredacted or ungrounded review.
    with pytest.raises(NotImplementedError):
        build_review_service(Container(_settings("onprem"))).review(complaint, actor="parity@test")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
