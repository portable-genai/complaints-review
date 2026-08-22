"""Unit tests for the review policy, serialization, Settings.load and Container wiring.

* ComplaintReviewPolicy: a review always requires review; the draft is never sendable;
  high-stakes flags / severities escalate to a senior checker (P-06).
* domain/serialization.to_jsonable round-trips enums (-> .value) and datetimes.
* Settings.load parses config/settings.yaml.
* Container under profile=onprem binds the on-prem placeholder adapters with structural
  parity to their Protocols.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from tests.conftest import load_policy
from tests.fixtures import sample_complaints

from complaints_review import ports
from complaints_review.config import Container, Settings
from complaints_review.domain.models import (
    AuditEvent,
    Categorization,
    ComplaintCategory,
    ConductFlag,
    ConductFlagKind,
    Decision,
    RootCause,
    Severity,
    SourceType,
)

CONFIG_PATH = "config/settings.yaml"

PORT_PROTOCOLS = {
    "extraction": ports.DocumentExtractionPort,
    "knowledge_base": ports.KnowledgeBaseClientPort,
    "llm": ports.LLMPort,
    "guardrail": ports.GuardrailPort,
    "redaction": ports.PIIRedactionPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
}


# --------------------------------------------------------------------------- #
# ComplaintReviewPolicy (P-06)
# --------------------------------------------------------------------------- #
def test_review_always_required():
    policy = load_policy("ComplaintReviewPolicy")()
    assert policy.requires_review() is True


def test_draft_is_never_sendable_by_system():
    policy = load_policy("ComplaintReviewPolicy")()
    assert policy.draft_is_sendable() is False


def test_escalates_on_systemic_flag():
    policy = load_policy("ComplaintReviewPolicy")()
    flags = (ConductFlag(kind=ConductFlagKind.SYSTEMIC_ISSUE, severity=Severity.HIGH, detail="x"),)
    assert policy.escalates(flags, Severity.LOW) is True


def test_escalates_on_vulnerable_customer_flag():
    policy = load_policy("ComplaintReviewPolicy")()
    flags = (
        ConductFlag(kind=ConductFlagKind.VULNERABLE_CUSTOMER, severity=Severity.HIGH, detail="x"),
    )
    assert policy.escalates(flags, None) is True


def test_escalates_on_high_severity_even_without_flags():
    policy = load_policy("ComplaintReviewPolicy")()
    assert policy.escalates((), Severity.CRITICAL) is True


def test_does_not_escalate_on_low_severity_deadline_only():
    policy = load_policy("ComplaintReviewPolicy")()
    flags = (ConductFlag(kind=ConductFlagKind.DEADLINE_RISK, severity=Severity.MEDIUM, detail="x"),)
    assert policy.escalates(flags, Severity.MEDIUM) is False


# --------------------------------------------------------------------------- #
# to_jsonable
# --------------------------------------------------------------------------- #
def _to_jsonable():
    from complaints_review.domain.serialization import to_jsonable

    return to_jsonable


def test_to_jsonable_enum_becomes_value():
    to_jsonable = _to_jsonable()
    assert to_jsonable(ComplaintCategory.MIS_SELLING) == "mis_selling"
    assert to_jsonable(Severity.HIGH) == "high"
    assert to_jsonable(Decision.BLOCKED) == "blocked"
    assert to_jsonable(SourceType.POLICY) == "policy"


def test_to_jsonable_datetime_is_json_safe_string():
    to_jsonable = _to_jsonable()
    dt = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    out = to_jsonable(dt)
    assert isinstance(out, str)
    assert json.loads(json.dumps(out)) == out
    assert "2026-06-20" in out


def test_to_jsonable_categorization_roundtrips_through_json():
    to_jsonable = _to_jsonable()
    categorization = Categorization(
        category=ComplaintCategory.FEES_CHARGES,
        root_cause=RootCause(description="unexpected fee", systemic=True),
        severity=Severity.MEDIUM,
        regulatory_relevance=("fair-dealing",),
        citations=(sample_complaints.PRIMARY_PASSAGE.citation,),
    )
    out = to_jsonable(categorization)
    text = json.dumps(out)
    reloaded = json.loads(text)
    assert reloaded["category"] == "fees_charges"
    assert reloaded["root_cause"]["systemic"] is True
    assert reloaded["citations"][0]["source_type"] == "policy"


def test_to_jsonable_audit_event_is_worm_serialisable():
    to_jsonable = _to_jsonable()
    event = AuditEvent(
        action="review",
        actor="conduct-officer",
        decision=Decision.ESCALATED,
        redacted_prompt="[NRIC]",
        redacted_response="summary",
        citations=(sample_complaints.PRIMARY_PASSAGE.citation,),
    )
    out = to_jsonable(event)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["decision"] == "escalated"
    assert reloaded["action"] == "review"


# --------------------------------------------------------------------------- #
# Settings.load + Container wiring
# --------------------------------------------------------------------------- #
def test_settings_load_parses_yaml():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "asia-southeast1"
    assert settings.models.reasoning == "gemini-3.5-flash"
    assert settings.models.triage == "gemini-3.1-flash-lite"
    assert settings.document_ai.location == "asia-southeast1"
    assert settings.policy.deadline_days == 21
    assert "vulnerable_customer" in settings.policy.escalating_flags
    assert set(PORT_PROTOCOLS) <= set(settings.adapters)


def test_policy_refuses_invalid_values_at_configuration() -> None:
    from complaints_review.config import PolicySettings

    with pytest.raises(ValueError, match="greater than zero"):
        PolicySettings(deadline_days=0)
    with pytest.raises(ValueError, match="unknown values"):
        PolicySettings(escalating_flags=("vulnerable-customer",))
    with pytest.raises(ValueError, match="unknown values"):
        PolicySettings(high_severities=("severe",))


def test_settings_pins_models_to_allowed_ids():
    settings = Settings.load(CONFIG_PATH)
    assert settings.models.reasoning != "gemini-2.0-flash"
    assert settings.models.triage != "gemini-2.0-flash"
    assert settings.models.reasoning.startswith("gemini-3")


def _onprem_settings() -> Settings:
    s = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=s.project_id,
        region=s.region,
        profile="onprem",
        kms_key=s.kms_key,
        grounding_enabled=s.grounding_enabled,
        models=s.models,
        document_ai=s.document_ai,
        agent_search=s.agent_search,
        model_armor=s.model_armor,
        dlp=s.dlp,
        logging=s.logging,
        agent_engine=s.agent_engine,
        adapters=s.adapters,
    )


def test_container_binds_onprem_adapters_with_protocol_parity():
    container = Container(_onprem_settings())
    for port_name, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port_name)
        assert isinstance(adapter, protocol), (
            f"on-prem adapter for '{port_name}' is not structurally a {protocol.__name__}"
        )


def test_container_falls_back_to_gcp_binding_when_profile_missing():
    settings = _onprem_settings()
    binding = settings.adapters["guardrail"]
    assert binding["onprem"].endswith("OnPremGuardrailAdapter")
    assert "gcp" in binding  # gcp is always present as the primary/fallback


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
