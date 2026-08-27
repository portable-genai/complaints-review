"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` : proof of the
ports-and-adapters / no-lock-in principle (P-02). Every adapter follows one construction
convention: ``Adapter(settings: Settings)``.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting

from .envread import read_env_setting, setting_or_default

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

#: The one environment variable that selects the runtime profile. Only :func:`resolve_profile`
#: may read it; ``tests/unit/test_profile_single_source.py`` fails the build if another module
#: re-derives the profile with its own permissive default.
_PROFILE_ENV = "COMPLAINTS_PROFILE"

#: Every profile the adapter table binds. An exact, case-sensitive membership test, so a
#: mis-capitalised value is a boot failure rather than a profile that matches no posture.
RUNTIME_PROFILES = frozenset({"local", "gcp", "platform", "onprem"})

#: The profile string handed to every INTERNET-FACING relaxation when ``COMPLAINTS_PROFILE``
#: was never set. Deliberately NOT a member of :data:`RUNTIME_PROFILES` and it never reaches
#: an adapter binding: it exists so that "no choice was made" is a distinct input to the
#: security layers rather than being indistinguishable from a deliberately chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of ``COMPLAINTS_PROFILE``, and what each consumer must key off.

    The two derived strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent a choice this is still ``local``, because the
    #: alternative is importing cloud SDKs that are not installed; what an unconsented run
    #: loses is the identity relaxation, not the SDK-free data adapters.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (``COMPLAINTS_PROFILE`` set, or ``profile:``
    #: written into the settings file)? Direct construction is deliberate by definition, so
    #: the default is True and only :meth:`Settings.load` can produce False.
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off: the CORS allowlist, the dev personas.

        These grant something extra to ``local``, so an unconsented run must NOT look like
        ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's allowlist and
        no persona's profile.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay confined.
        """
        return self.profile if self.explicit else "local"


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo.

    The comparison is exact and case-sensitive on purpose. Without it
    ``COMPLAINTS_PROFILE=Local`` matched no entry in the adapter table, and
    the adapter table. The container requires an exact binding too, so neither a typo nor an
    incomplete profile can silently select managed cloud adapters.
    """
    if profile not in RUNTIME_PROFILES:
        allowed = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {allowed}")
    return profile


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    """The three states of ``COMPLAINTS_PROFILE``, from the real environment or an injected one.

    The injected-mapping branch rebuilds the same ``EnvSetting`` by hand because a caller's
    ``Mapping`` has no three-state accessor; going through ``.get(name, "")`` here would be the
    very collapse this resolver exists to remove, only hidden behind a test seam.
    """
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(
    environ: Mapping[str, str] | None = None, *, file_profile: str = ""
) -> ProfileChoice:
    """Read the profile once: ABSENT is no choice, EMPTIED refuses, a value is validated.

    Resolution is three-state, and the middle state is the one most easily lost. Unset is
    not a member of the valid set at all, so the run is unconsented; set-and-empty is an
    expressed intent that names no profile, so it refuses rather than inheriting the
    unconsented posture; set-and-valid is carried through; set-and-invalid raises here rather
    than at the first request, so a typo is a boot failure. ``file_profile`` is the settings
    file's own ``profile:`` key, which counts as a deliberate choice when it names a profile;
    the shipped file leaves it as ``${COMPLAINTS_PROFILE}`` so an unset variable stays unset
    instead of materialising there as a written-down ``local``.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value; unset it for the unconsented "
            "loopback-only posture, or name a supported profile."
        )
    if setting.has_value:
        return ProfileChoice(profile=_validate_profile(setting.value), explicit=True)
    chosen = file_profile.strip()
    if chosen:
        return ProfileChoice(profile=_validate_profile(chosen), explicit=True)
    return ProfileChoice(profile="local", explicit=False)


def _interpolate(value: Any) -> Any:
    """Replace ``${VAR}`` / ``${VAR:-default}`` tokens recursively, in THREE states not two.

    ``${VAR:-default}`` in ``settings.yaml`` is the same construct as
    ``setting_or_default(name, default)`` one layer down: a documented default that a variable is
    allowed to override. It obeys the same rule, and it delegates to the same helper so there is
    exactly one implementation of that rule. UNSET takes the written default, SET-AND-EMPTY
    RAISES ``ConfiguredEmptyError``, SET-AND-VALID wins.

    Resolving an emptied variable to the empty string was the two-state collapse in the other
    direction: it made ``${VAR:-http://audit:8080}`` with ``VAR=""`` indistinguishable from
    ``${VAR:-}``, so an operator who emptied a variable got a value nobody reviewed, and for a
    base URL, an allowlist or a path the empty string is the permissive branch. This raises at
    import, which takes the whole process down rather than one feature; that is the correct
    trade, because the failure is a configuration error made seconds earlier and it surfaces as
    a deploy-time crashloop naming the variable, not as production traffic served with a posture
    nobody chose. ``resolve_profile`` above already refuses at import for exactly this class.

    ``${VAR}`` with no ``:-`` is ``setting_or_default(name, "")``: unset yields the empty string,
    emptied still refuses.
    """
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            return setting_or_default(m.group(1), m.group(2) or "")

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.5-flash"
    triage: str = "gemini-3.5-flash"
    hard_reasoning: str = "gemini-3.5-flash"  # Preview : feature-flagged off by default
    use_hard_reasoning: bool = False


@dataclass(frozen=True)
class DocumentAiSettings:
    location: str = "asia-southeast1"
    processor_id: str = ""  # the Document AI processor resource id
    processor_version: str = ""  # optional pinned processor version


@dataclass(frozen=True)
class AgentSearchSettings:
    data_store_id: str = "complaints-policy-kb"
    location: str = "asia-southeast1"
    serving_config: str = "default_search"
    engine_id: str = "complaints-review-engine"


@dataclass(frozen=True)
class ModelArmorSettings:
    template_id: str = "complaints-guardrail"
    host: str = "modelarmor.asia-southeast1.rep.googleapis.com"


@dataclass(frozen=True)
class DlpSettings:
    inspect_template: str = ""  # projects/.../inspectTemplates/...
    deidentify_template: str = ""  # projects/.../deidentifyTemplates/...


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "complaints-review-audit"
    bucket: str = "complaints-review-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "complaints-review"


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + append-only audit).

    Empty strings select the per-package default under ``~/.complaints_review/``; tests
    pass ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here.
    """

    db_path: str = ""  # SQLite FTS5 knowledge-base index; "" => ~/.complaints_review/local.db
    audit_path: str = ""  # append-only audit store;       "" => ~/.complaints_review/audit.db


@dataclass(frozen=True)
class PiiSettings:
    """Which jurisdictions' PII the redactor masks (drives the shared ``pii-kit`` rows).

    B6's complaint files carry APAC retail-banking customer PII, so SG / HK / JP / AU national
    ids (plus universal email / phone) are the default. The local redactor, the DLP custom info
    types and the eval leak-check all read the same ``pii-kit`` rows for these jurisdictions, so
    the set is configured once here rather than hard-coded in three places.
    """

    jurisdictions: tuple[str, ...] = ("SG", "HK", "JP", "AU")


@dataclass(frozen=True)
class PolicySettings:
    """Adopter-owned complaint policy expressed as portable strings and numbers."""

    deadline_days: int = 21
    vulnerability_keywords: tuple[str, ...] = (
        "vulnerable",
        "bereave",
        "bereaved",
        "disab",
        "mental health",
        "illness",
        "terminal",
        "elderly",
        "dementia",
        "financial hardship",
        "hardship",
        "distress",
        "suicid",
    )
    escalating_flags: tuple[str, ...] = (
        "systemic_issue",
        "regulatory_breach",
        "vulnerable_customer",
    )
    high_severities: tuple[str, ...] = ("high", "critical")

    def __post_init__(self) -> None:
        if self.deadline_days <= 0:
            raise ValueError("policy.deadline_days must be greater than zero")
        from .domain.models import ConductFlagKind, Severity

        flag_values = {item.value for item in ConductFlagKind}
        severity_values = {item.value for item in Severity}
        unknown_flags = sorted(set(self.escalating_flags) - flag_values)
        unknown_severities = sorted(set(self.high_severities) - severity_values)
        if unknown_flags:
            raise ValueError(f"policy.escalating_flags contains unknown values: {unknown_flags}")
        if unknown_severities:
            raise ValueError(
                f"policy.high_severities contains unknown values: {unknown_severities}"
            )


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = "asia-southeast1"
    # gcp | local | platform | onprem. local is the SDK-free adapter family; prod sets
    # COMPLAINTS_PROFILE=gcp explicitly.
    profile: str = "local"
    # Was the profile CHOSEN, or merely inherited because nothing named one? ``load`` sets
    # this False when neither ``COMPLAINTS_PROFILE`` nor the settings file's ``profile:`` key
    # names a profile. Direct construction is deliberate by definition (a caller named it in
    # code), so the default is True. See :attr:`exposure_profile` for what it gates.
    profile_explicit: bool = True
    kms_key: str = ""  # projects/.../cryptoKeys/... (regional)
    grounding_enabled: bool = False
    models: ModelSettings = field(default_factory=ModelSettings)
    document_ai: DocumentAiSettings = field(default_factory=DocumentAiSettings)
    agent_search: AgentSearchSettings = field(default_factory=AgentSearchSettings)
    model_armor: ModelArmorSettings = field(default_factory=ModelArmorSettings)
    dlp: DlpSettings = field(default_factory=DlpSettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    pii: PiiSettings = field(default_factory=PiiSettings)
    policy: PolicySettings = field(default_factory=PolicySettings)
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def exposure_profile(self) -> str:
        """The profile every RELAXATION keys off, never the raw :attr:`profile`."""
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit).exposure_profile

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off; ``local`` is the RESTRICTIVE case there."""
        return ProfileChoice(profile=self.profile, explicit=self.profile_explicit).bind_profile

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        path = Path(path or setting_or_default("COMPLAINTS_SETTINGS", "config/settings.yaml"))
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        nested: dict[str, Any] = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "document_ai": DocumentAiSettings(**(raw.pop("document_ai", {}) or {})),
            "agent_search": AgentSearchSettings(**(raw.pop("agent_search", {}) or {})),
            "model_armor": ModelArmorSettings(**(raw.pop("model_armor", {}) or {})),
            "dlp": DlpSettings(**(raw.pop("dlp", {}) or {})),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
            "pii": _pii_settings(raw.pop("pii", {}) or {}),
            "policy": _policy_settings(raw.pop("policy", {}) or {}),
        }
        choice = resolve_profile(file_profile=str(raw.pop("profile", "") or ""))
        known = {f for f in Settings.__dataclass_fields__ if f not in nested}
        flat = {k: v for k, v in raw.items() if k in known}
        flat.pop("profile_explicit", None)  # never settable from the settings file
        return Settings(profile=choice.profile, profile_explicit=choice.explicit, **flat, **nested)


def _pii_settings(raw: dict[str, Any]) -> PiiSettings:
    """Build PiiSettings from raw YAML, coercing a jurisdictions list to a tuple."""
    js = raw.get("jurisdictions")
    if js is None:
        return PiiSettings()
    return PiiSettings(jurisdictions=tuple(str(j).strip().upper() for j in js if str(j).strip()))


def _policy_settings(raw: dict[str, Any]) -> PolicySettings:
    for key in ("vulnerability_keywords", "escalating_flags", "high_severities"):
        if key in raw:
            raw[key] = tuple(str(value).strip().lower() for value in raw[key] if str(value).strip())
    if "deadline_days" in raw:
        raw["deadline_days"] = int(raw["deadline_days"])
    return PolicySettings(**raw)


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the
    on-prem profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def extraction(self) -> Any:
        return self._bind("extraction")

    @cached_property
    def knowledge_base(self) -> Any:
        return self._bind("knowledge_base")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def guardrail(self) -> Any:
        return self._bind("guardrail")

    @cached_property
    def redaction(self) -> Any:
        return self._bind("redaction")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def registry(self) -> Any:
        return self._bind("registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")

    @cached_property
    def review_router(self) -> Any:
        return self._bind("review_router")


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same ``adapters:`` table the container binds from, INCLUDING its fallback for a
    profile the table does not list, so a deployment is answered about the adapter it ACTUALLY
    runs rather than the one the profile name suggests. A deployment that rebound identity in
    ``config/settings.yaml`` (the documented on-premises path: swap the placeholder for the
    client's own IdP adapter) is answered about that.

    Constructing is deliberately avoided: the seeded-persona adapter REFUSES to construct
    under an inherited profile, so a posture computed from an instance would be unobtainable
    in one of the exact cases it has to describe.
    """
    binding = settings.adapters.get("identity", {})
    dotted = binding.get(settings.profile)
    if not dotted:
        raise KeyError(f"No identity adapter configured under profile '{settings.profile}'.")
    module_path, _, class_name = dotted.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {dotted!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: neither the profile string nor the presence of a
    service-to-service secret can answer it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
