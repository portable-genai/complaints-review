"""What the model pill states before any answer must be true of the profile the service runs.

Every served console shows two small pills at the top right (owner decision, 2026-09-23, which
replaced the full-width provenance banner): the model that ANSWERED, and ``Search`` when the
answer used an online search tool. Until a request is answered, the model pill shows WHICH model
the bound generator calls, titled with WHERE the process runs, and both come from ``/healthz``
because the browser cannot know either: a console that read its runtime from
``window.location`` would be right until the day the deployment served through a proxy, and
wrong silently after that. The answered half is ``tests/unit/test_answer_provenance.py``.

The reason this is worth a test rather than a glance is what the pill is FOR. These systems are
demonstrated on a laptop and on a deployment, sometimes in the same hour, and a screenshot of one
is indistinguishable from the other. A pill that was merely present but wrong is worse than no
pill: it converts "the viewer does not know" into "the viewer has been told the wrong thing", and
the wrong thing here is whether a figure came from a managed model or from a deterministic
offline stub.

So the assertions below are about AGREEMENT with the profile, not about presence.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from complaints_review.config import Settings

CONFIG_PATH = Path("config/settings.yaml")

#: Answers that mean "no managed model produced this". Each says something different and the
#: difference is the point, which is why this is a set rather than one sentinel:
#: ``deterministic-offline-stub`` says a model-shaped port is bound to a stub;
#: ``no-model`` says there is no such port at all; ``onprem-not-implemented`` says the port
#: exists and refuses. A reviewer approving an escalation is entitled to know which they read.
_NON_MANAGED_ANSWERS = frozenset(
    {
        "deterministic-offline-stub",
        "no-model",
        "onprem-not-implemented",
        "managed-model-unavailable",
    }
)


def _for_profile(profile: str) -> Settings:
    return dataclasses.replace(Settings.load(CONFIG_PATH), profile=profile)


@pytest.mark.parametrize("profile", ["local", "gcp", "onprem"])
def test_the_runtime_half_states_where_the_process_runs(profile: str) -> None:
    """``onprem`` reads ``local``, because that is its entire point.

    A managed model call does not make a process cloud-hosted. This half is about where the
    PROCESS runs and the other half is about whose model answers, and collapsing the two is how
    an on-premises deployment ends up describing itself as running on GCP.
    """
    settings = _for_profile(profile)
    assert settings.runtime == ("gcp" if profile == "gcp" else "local")


@pytest.mark.parametrize("profile", ["local", "gcp", "onprem"])
def test_the_model_half_is_always_answered(profile: str) -> None:
    """A blank is not an option: the pill renders nothing rather than render a falsehood."""
    assert _for_profile(profile).generator_model.strip()


@pytest.mark.parametrize("profile", ["local", "onprem"])
def test_no_offline_profile_claims_a_managed_model(profile: str) -> None:
    """The defect that matters, stated as an assertion.

    A laptop run naming a Gemini model is precisely the confusion the pill exists to remove,
    and it is the one direction a reviewer cannot detect by looking at the page.
    """
    answer = _for_profile(profile).generator_model
    assert answer in _NON_MANAGED_ANSWERS, (
        f"the {profile!r} profile reports {answer!r}, which reads as a managed model answering "
        "a request that never left the machine"
    )


def test_the_health_contract_carries_both_halves() -> None:
    """The wire contract the console actually reads. A property nothing serves is not a contract.

    Asserted on the response MODEL rather than by calling ``/healthz`` through a test client.
    That is not a convenience: under the ``local`` posture these services deliberately refuse an
    unauthenticated non-loopback peer, so a client call here would exercise that refusal instead
    of this contract, and the refusal already has its own tests. What must not rot is that the
    two fields exist on the response the endpoint returns.
    """
    from complaints_review.api.schemas import HealthResponse

    fields = set(HealthResponse.model_fields)
    assert "runtime" in fields, "the console reads runtime off /healthz and the field is absent"
    assert "generator_model" in fields


def test_the_endpoint_answers_from_settings_rather_than_a_literal() -> None:
    """A pill value hard-coded at the endpoint would be right once and wrong after the next rebind.

    Both halves are properties of :class:`Settings`, so the values the endpoint sends are the
    values the profile implies; this pins that they are readable and non-empty together, which
    is what the endpoint relies on.
    """
    settings = Settings.load(CONFIG_PATH)
    assert settings.runtime in {"gcp", "local"}
    assert settings.generator_model.strip()


def test_the_managed_profile_names_a_model_or_says_exactly_why_not() -> None:
    """No placeholder survives here: every answer is a model id or a stated reason.

    ``managed-model-unnamed`` used to be a real answer in twenty-five trees, and it was the
    resolver looking in the wrong place rather than the trees being silent -- most of the fleet
    pins the id in settings under a per-repository field name. It is kept only as a defensive
    fallback and no tree should reach it.
    """
    answer = _for_profile("gcp").generator_model
    assert answer != "managed-model-unnamed", (
        "the managed model id is not being resolved from anywhere: set _GENERATOR_MODEL_ATTR "
        "to the settings path holding it, or declare _MODEL on the bound adapter"
    )
    assert answer.strip()


def test_not_implemented_is_claimed_only_by_an_adapter_that_never_calls_a_model() -> None:
    """The one answer that is INFERRED rather than read, so it is the one that can be wrong.

    ``managed-not-implemented`` is reached when a tree names no settings path and its adapter
    declares no model constant. That is correct for a deployment-wired placeholder, and a LIE
    for an adapter that generates while declaring nothing.

    The check is "does it call the model API", not "does it raise". Raising was tried first and
    is too weak: it passed `soc-fraud-fusion`, which generates and also raises on bad input, and
    it had already let a real mis-classification through -- `conversation-qa-scorecard` calls
    ``generate_content`` and raises only when its model is unconfigured, and was grouped with
    the placeholders on the strength of that raise. Its model is named now.
    """
    from importlib import import_module
    from pathlib import Path as _Path

    # The MANAGED profile, not whatever the settings file defaults to. Reading the default
    # profile here made this test inert: offline it answers `deterministic-offline-stub`, so it
    # returned before checking anything, and it passed a deliberately broken tree.
    settings = _for_profile("gcp")
    if settings.generator_model != "managed-not-implemented":
        return
    from complaints_review.config import _GENERATOR_PORT

    binding = str((settings.adapters.get(_GENERATOR_PORT) or {}).get("gcp", ""))
    module = import_module(binding.partition(":")[0])
    source = _Path(module.__file__ or "").read_text()
    for call in ("generate_content", ".predict(", ".invoke("):
        assert call not in source, (
            f"{binding} reports managed-not-implemented but calls {call!r}: it generates, so "
            "the model it calls must be named rather than declared absent"
        )


def test_the_pills_call_a_base_this_console_actually_serves() -> None:
    """The half of the contract that lives in the BROWSER, and the half that was once broken.

    The banner these pills replaced fetched ``/api/agent/healthz``, the same-origin route handler
    the service template ships. This console does not ship one; it calls its backend directly on
    ``NEXT_PUBLIC_API_BASE``. So the health call 404'd, took the failure branch, and the failure
    branch renders nothing, deliberately, because a pill that guessed would assert provenance it
    does not have. A check that cannot fail loudly fails as an ABSENCE.

    Both architectures are legitimate, so this pins AGREEMENT rather than a literal: a tree with
    ``ui/app/api/agent`` proxies through its own origin and the pills should name that path; a
    tree without one must read the same base the rest of its console reads, and so must the
    fetch wrapper that reads the answered headers.
    """
    pills = Path("ui/app/ModelPills.tsx").read_text()
    proxies_through_own_origin = Path("ui/app/api/agent").is_dir()

    assert ('"/api/agent"' in pills) == proxies_through_own_origin, (
        "the pills name /api/agent but this console has no route handler at ui/app/api/agent, "
        "so the health call reaches nothing and the pills render nothing"
        if not proxies_through_own_origin
        else "this console ships a /api/agent route handler but the pills do not use it"
    )

    if not proxies_through_own_origin:
        assert "API_BASE" in pills, (
            "the pills must resolve their base the way the rest of the console does, through "
            "the NEXT_PUBLIC_API_BASE reader in ui/lib/api.ts"
        )
        assert "watchAnswers(window, API_BASE," in pills, (
            "the answered headers must be read off responses from the same base the console "
            "calls, or no answer ever reaches the pill"
        )


def test_the_pills_read_health_and_both_answer_headers() -> None:
    """The pills contract: mounted in the layout, configured from /healthz, answered by headers."""
    pills = Path("ui/app/ModelPills.tsx").read_text()
    helper = Path("ui/lib/answer-provenance.mjs").read_text()
    layout = Path("ui/app/layout.tsx").read_text()

    assert "<ModelPills />" in layout
    assert "/healthz" in pills
    assert "generator_model" in pills and "runtime" in pills
    assert '"x-answered-by"' in helper
    assert '"x-search-used"' in helper
    assert not Path("ui/app/ProvenanceBanner.tsx").exists(), "the banner must be gone, not shimmed"


def test_the_service_exposes_both_headers_to_this_console() -> None:
    """With no same-origin proxy to forward them, the service's CORS policy must expose them.

    A standalone console calls the service cross-origin, and the browser hides any response
    header CORS does not name, so without this the service sends both headers and the pill
    never sees either. The runtime proof is in ``test_answer_provenance.py``; this pins the
    source so a rewrite of the CORS block cannot drop them unnoticed.
    """
    source = Path("src/complaints_review/api/app.py").read_text()
    assert "install_answer_provenance(app)" in source
    assert "provenance.ANSWERED_BY_HEADER" in source
    assert "provenance.SEARCH_USED_HEADER" in source


def _rule(css: str, selector: str) -> str:
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


def test_the_pills_sit_at_the_top_right_in_a_light_only_console() -> None:
    """Fixed at the top right, and with no dark-scheme override in a console that stays light.

    The template's pills invert under ``prefers-color-scheme: dark``. This console pins
    ``color-scheme: light`` and never darkens, so that override would render a dark "configured"
    pill and a pale "answered" pill against a light page: the two states read backwards.
    """
    css = Path("ui/app/globals.css").read_text()
    block = _rule(css, ".model-pills")
    assert "position: fixed" in block
    assert "top:" in block and "right:" in block
    assert "color-scheme: light" in css
    assert "prefers-color-scheme: dark" not in css
    assert ".provenance-banner" not in css
