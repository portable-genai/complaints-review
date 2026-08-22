"""Contract tests: the ``onprem`` and ``local`` adapters are structural parity of the ports.

For every port the catalog declares, this iterates the adapter map and, for both the
``onprem`` and ``local`` profiles, imports + constructs the bound class (which must build
cleanly with **no Google Cloud SDK** installed), then asserts:

  1. the constructed instance satisfies its runtime_checkable Protocol (isinstance), and
  2. every method/property the Protocol declares actually exists on the instance.

It additionally proves the two profiles' distinct contracts:

* ``onprem`` is the fail-fast Google Distributed Cloud migration target: every method
  raises ``NotImplementedError`` (proven on a representative port), and
* ``local`` is a WORKING offline stack: the same ports construct and answer in-process.

This is the proof of the ports-and-adapters / no-lock-in promise (P-02): the on-prem
migration target and the offline local stack implement the exact same interface as the
managed GCP stack.
"""

from __future__ import annotations

from typing import Protocol, get_type_hints

import pytest

from complaints_review import config, ports
from complaints_review.config import LocalSettings, Settings, instantiate

CONFIG_PATH = "config/settings.yaml"

# Every port name in settings.adapters mapped to its Protocol.
PORT_PROTOCOLS: dict[str, type] = {
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
    "identity": ports.IdentityPort,
    "review_router": ports.ReviewRouterPort,
}

# Profiles whose adapters must construct + satisfy the Protocols with no GCP SDK.
SDK_FREE_PROFILES = ("onprem", "local")


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    # Point the local stores at in-memory SQLite so the contract test stays ephemeral.
    return Settings(
        project_id=base.project_id,
        region=base.region,
        profile=profile,
        kms_key=base.kms_key,
        grounding_enabled=base.grounding_enabled,
        models=base.models,
        document_ai=base.document_ai,
        agent_search=base.agent_search,
        model_armor=base.model_armor,
        dlp=base.dlp,
        logging=base.logging,
        agent_engine=base.agent_engine,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )


def _protocol_members(protocol: type) -> set[str]:
    """The attribute names a Protocol declares (methods + properties), no dunders."""
    members = set(getattr(protocol, "__protocol_attrs__", set()))
    if not members:
        # Fallback for older typing internals: union of annotations + callables.
        members |= set(get_type_hints(protocol).keys())
        for name in dir(protocol):
            if name.startswith("_"):
                continue
            members.add(name)
    return {m for m in members if not m.startswith("_")}


def test_port_protocols_matches_settings_adapters():
    """The hand-maintained PORT_PROTOCOLS map must equal the ports bound in settings.

    Without this, a fork that adds a port Protocol and binds it in config/settings.yaml but
    forgets the PORT_PROTOCOLS entry gets ZERO parity/constructor/onprem-binding enforcement
    with a green CI (silent drift): the parametrized suites only iterate PORT_PROTOCOLS, so a
    binding it omits is never constructed or checked. The reverse omission (a name in the map
    with no binding) would make the other tests KeyError obscurely. Set-equality here fails
    loudly on EITHER omission, so the map and config/settings.yaml can never drift apart.
    """
    settings = Settings.load(CONFIG_PATH)
    bound = set(settings.adapters)
    declared = set(PORT_PROTOCOLS)
    missing_from_map = bound - declared
    missing_from_settings = declared - bound
    assert not missing_from_map, (
        f"ports bound in settings.adapters but absent from PORT_PROTOCOLS "
        f"(so untested): {sorted(missing_from_map)}. Add them to the parity map."
    )
    assert not missing_from_settings, (
        f"ports in PORT_PROTOCOLS with no settings.adapters binding: "
        f"{sorted(missing_from_settings)}."
    )


def test_every_port_has_an_explicit_binding_for_every_profile():
    settings = Settings.load(CONFIG_PATH)
    for port_name in PORT_PROTOCOLS:
        binding = settings.adapters.get(port_name, {})
        missing = set(config.RUNTIME_PROFILES) - set(binding)
        assert not missing, f"port '{port_name}' has no explicit bindings for {sorted(missing)}"


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_satisfies_protocol(profile: str, port_name: str):
    settings = _settings(profile)
    protocol = PORT_PROTOCOLS[port_name]
    dotted = settings.adapters[port_name][profile]

    # Import + construct with only Settings (the adapter convention), no GCP SDK.
    adapter = instantiate(dotted, settings)

    # 1. Structural conformance via runtime_checkable Protocol.
    assert isinstance(adapter, protocol), (
        f"{dotted} does not structurally satisfy {protocol.__name__}"
    )

    # 2. Every declared Protocol member exists. Check on the *class* (via the MRO), not
    #    the instance: a placeholder property getter may raise, so ``hasattr`` would
    #    wrongly report it missing. Looking the name up on the type tests for declaration
    #    without invoking the getter.
    members = _protocol_members(protocol)
    declared = set().union(*(vars(klass) for klass in type(adapter).__mro__))
    for member in members:
        assert member in declared, (
            f"{dotted} is missing port method/attr '{member}' of {protocol.__name__}"
        )


@pytest.mark.parametrize("profile", SDK_FREE_PROFILES)
@pytest.mark.parametrize("port_name", sorted(PORT_PROTOCOLS))
def test_adapter_constructs_with_single_settings_arg(profile: str, port_name: str):
    """The build contract: every adapter is ``Adapter(settings: Settings)``."""
    settings = _settings(profile)
    dotted = settings.adapters[port_name][profile]
    module_path, _, class_name = dotted.partition(":")
    import importlib

    cls = getattr(importlib.import_module(module_path), class_name)
    # Must accept exactly one positional Settings argument and build cleanly.
    instance = cls(settings)
    assert instance is not None


def test_shared_types_are_the_commons_objects_not_local_copies():
    """Object IDENTITY, because structural conformance cannot see a look-alike copy.

    This repo used to declare its own ``ObservabilityTracerPort``, ``EvaluationGatePort``,
    ``TokenUsage``, ``EvalMetricResult`` and ``EvalReport`` by hand. Sixteen repositories had
    each done the same, and by the time anyone compared them they disagreed: one had dropped
    the evaluation port, two had dropped its ``gate`` method, one returned ``str`` from an
    audit ``record`` that returns ``None`` everywhere else. A Protocol copied into N repos is
    N Protocols, and only one of them gets fixed when a defect is found.

    ``isinstance`` against a ``runtime_checkable`` Protocol passes for a look-alike copy, and
    so does every structural test above: that is exactly how the drift stayed invisible. ``is``
    does not. If someone re-declares one of these locally, this fails on the next run.
    """
    import agent_eval_kit
    import hex_service_kit.observability as commons_obs

    from complaints_review.domain import models

    assert ports.ObservabilityTracerPort is commons_obs.ObservabilityTracerPort
    assert ports.TokenUsage is commons_obs.TokenUsage
    assert ports.EvaluationGatePort is agent_eval_kit.EvaluationGatePort
    assert models.TokenUsage is commons_obs.TokenUsage
    assert models.EvalReport is agent_eval_kit.EvalReport
    assert models.EvalMetricResult is agent_eval_kit.EvalMetricResult


def test_onprem_knowledge_base_fails_fast():
    """The on-prem stubs are fail-fast: a representative port raises NotImplementedError."""
    settings = _settings("onprem")
    adapter = instantiate(settings.adapters["knowledge_base"]["onprem"], settings)
    from complaints_review.domain.models import RetrievalQuery

    with pytest.raises(NotImplementedError):
        adapter.search(RetrievalQuery(text="anything"))


def test_local_knowledge_base_returns_real_passages():
    """The local stack is WORKING: retrieval returns real, page-cited passages offline."""
    settings = _settings("local")
    adapter = instantiate(settings.adapters["knowledge_base"]["local"], settings)
    from complaints_review.domain.models import RetrievalQuery

    passages = adapter.search(
        RetrievalQuery(text="complaint handling policy fair dealing", top_k=5)
    )
    assert passages, "local FTS5 retrieval returned nothing for the seeded corpus"
    assert all(p.citation.page is not None for p in passages), "page-level citation required"


def test_all_protocols_are_runtime_checkable():
    for protocol in PORT_PROTOCOLS.values():
        assert issubclass(protocol, Protocol)  # type: ignore[arg-type]
        assert getattr(protocol, "_is_runtime_protocol", False), (
            f"{protocol.__name__} must be @runtime_checkable"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
