"""The profile has ONE source of truth, and it fails closed on an unset variable.

Mirrors human-review-console (``human-review-console/tests/test_profile_single_source.py``) as the
standing gate for the absence-read-as-consent class. The lesson it encodes: guarding the
identity adapter alone leaves another module re-deriving the same decision with its own raw
fallback, which is how the write path stays open. A drift guard is therefore part of the
defence, not a nicety: any module that reads
``COMPLAINTS_PROFILE`` directly can reintroduce the whole class, so only
``config.resolve_profile`` may read it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from complaints_review.api.app import _cors_origins, _frame_ancestors, _frame_options
from complaints_review.config import (
    RUNTIME_PROFILES,
    UNCONSENTED_PROFILE,
    Settings,
    _interpolate,
    resolve_profile,
)
from complaints_review.envread import ConfiguredEmptyError

_SRC = Path(__file__).resolve().parents[2] / "src" / "complaints_review"
_CONFIG = _SRC / "config.py"


def _python_sources() -> list[Path]:
    return sorted(p for p in _SRC.rglob("*.py") if p != _CONFIG)


def test_only_the_resolver_reads_the_profile_variable_from_the_environment() -> None:
    offenders = []
    for path in _python_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if re.search(r"(os\.environ|os\.getenv)[^\n]*COMPLAINTS_PROFILE", line):
                offenders.append(f"{path.relative_to(_SRC)}:{number}: {line.strip()}")
    assert not offenders, (
        "these modules re-derive the profile instead of calling config.resolve_profile, so "
        "an unset COMPLAINTS_PROFILE can again be read as consent:\n" + "\n".join(offenders)
    )


def test_the_scan_would_actually_fail_on_a_reintroduced_permissive_default() -> None:
    """The guard is only worth having if it fires; prove the pattern it looks for."""
    offending = 'profile = os.environ.get("COMPLAINTS_PROFILE", "local")'
    assert re.search(r"(os\.environ|os\.getenv)[^\n]*COMPLAINTS_PROFILE", offending)


def test_the_resolver_treats_only_an_absent_variable_as_no_choice() -> None:
    choice = resolve_profile({})
    assert choice.explicit is False
    assert choice.profile == "local"


@pytest.mark.parametrize("value", ["", "   "])
def test_a_configured_empty_profile_refuses_instead_of_inheriting_no_choice(value: str) -> None:
    """Split out of the case above, which would PIN the two-state read as if it were correct.

    Absent is still no choice. Set-and-empty is a THIRD state: an operator expressed an intent
    and it names no profile, so it refuses rather than quietly resolving to the unconsented
    posture the absent case gets.
    """
    with pytest.raises(ConfiguredEmptyError, match="COMPLAINTS_PROFILE"):
        resolve_profile({"COMPLAINTS_PROFILE": value})


def test_an_unconsented_run_is_not_the_local_profile_for_any_relaxation() -> None:
    choice = resolve_profile({})
    assert choice.exposure_profile == UNCONSENTED_PROFILE
    assert choice.exposure_profile != "local"
    assert UNCONSENTED_PROFILE not in RUNTIME_PROFILES


def test_an_unconsented_run_still_binds_loopback() -> None:
    """The bind guard fails closed in the OPPOSITE direction: local is the restrictive case."""
    assert resolve_profile({}).bind_profile == "local"


def test_a_deliberate_profile_is_carried_through_unchanged() -> None:
    for name in sorted(RUNTIME_PROFILES):
        choice = resolve_profile({"COMPLAINTS_PROFILE": name})
        assert (choice.profile, choice.explicit) == (name, True)
        assert choice.exposure_profile == name
        assert choice.bind_profile == name


def test_the_settings_file_key_counts_as_a_deliberate_choice() -> None:
    choice = resolve_profile({}, file_profile="gcp")
    assert (choice.profile, choice.explicit) == ("gcp", True)
    # The environment still wins over the file when both name a profile.
    assert resolve_profile({"COMPLAINTS_PROFILE": "local"}, file_profile="gcp").profile == "local"


@pytest.mark.parametrize("value", ["bogus", "Local", "GCP", "LOCAL", "live"])
def test_an_unknown_or_mis_capitalised_profile_is_refused_at_resolution(value: str) -> None:
    """A typo must not fall through Container._bind's documented gcp fallback, silently."""
    with pytest.raises(ValueError, match="unknown COMPLAINTS_PROFILE"):
        resolve_profile({"COMPLAINTS_PROFILE": value})


def test_settings_carry_the_choice_to_both_derived_profiles() -> None:
    unconsented = Settings(profile="local", profile_explicit=False)
    assert unconsented.exposure_profile == UNCONSENTED_PROFILE
    assert unconsented.bind_profile == "local"
    chosen = Settings(profile="local", profile_explicit=True)
    assert (chosen.exposure_profile, chosen.bind_profile) == ("local", "local")


def _clear_container() -> None:
    from complaints_review.api import deps

    deps.get_container.cache_clear()


def test_an_unconsented_run_gets_no_dev_cors_origins(monkeypatch) -> None:
    """RED before the three-state fix: the kit's dev fallback keys off the profile string."""
    monkeypatch.delenv("COMPLAINTS_PROFILE", raising=False)
    monkeypatch.delenv("COMPLAINTS_CORS_ORIGINS", raising=False)
    _clear_container()
    try:
        assert _cors_origins() == []
    finally:
        _clear_container()


def test_a_deliberate_local_run_keeps_the_dev_cors_origins(monkeypatch) -> None:
    """The companion case: choosing local deliberately keeps the offline demo working."""
    monkeypatch.setenv("COMPLAINTS_PROFILE", "local")
    monkeypatch.delenv("COMPLAINTS_CORS_ORIGINS", raising=False)
    _clear_container()
    try:
        assert _cors_origins() == ["http://localhost:3000", "http://127.0.0.1:3000"]
    finally:
        _clear_container()


def test_an_emptied_cors_allowlist_refuses_instead_of_reopening_the_dev_origins(
    monkeypatch,
) -> None:
    """Set-and-empty is a THIRD state: it refuses, it does not fall back to the relaxation."""
    monkeypatch.setenv("COMPLAINTS_PROFILE", "local")
    monkeypatch.setenv("COMPLAINTS_CORS_ORIGINS", "")
    _clear_container()
    try:
        assert _cors_origins() == []
    finally:
        _clear_container()


def test_an_emptied_frame_ancestors_refuses_framing_rather_than_dropping_the_directive() -> None:
    """An empty directive is a CSP parse error, so the restriction used to vanish entirely."""
    assert _frame_ancestors(None) == "'self'"
    assert _frame_ancestors("") == "'none'"
    assert _frame_ancestors("   ") == "'none'"
    assert _frame_ancestors("\n\t ") == "'none'"
    assert _frame_ancestors("https://parent.example") == "https://parent.example"


def test_the_refusing_state_still_carries_a_legacy_clickjacking_backstop() -> None:
    """Red before: the emptied state emitted CSP 'none' and NO X-Frame-Options at all.

    The old branch was ``== "'self'"``, so the operator who asked for the strictest posture
    got the weakest backstop: nothing. A browser predating frame-ancestors then had no
    clickjacking control on the very configuration that meant "nobody may frame this".
    ``'none'`` maps to DENY; a named parent origin correctly gets no header, because
    X-Frame-Options cannot express an allowlist and a DENY would break the intended embed.
    """
    assert _frame_options("'self'") == "SAMEORIGIN"
    assert _frame_options("'none'") == "DENY"
    assert _frame_options("https://parent.example") == ""
    assert _frame_options("https://parent.example https://portal.example") == ""


def test_the_emitted_headers_match_the_configured_state(monkeypatch) -> None:
    """End to end through the real middleware, not just the pure helpers.

    ``_FRAME_ANCESTORS`` is resolved once at import, so the emitted header is pinned to it;
    patch the module attribute to exercise each state against a live response.
    """
    from fastapi.testclient import TestClient

    from complaints_review.api import app as app_module

    expected = {
        "'self'": "SAMEORIGIN",
        "'none'": "DENY",
        "https://parent.example": None,
    }
    for ancestors, frame_options in expected.items():
        monkeypatch.setattr(app_module, "_FRAME_ANCESTORS", ancestors)
        with TestClient(app_module.app, client=("127.0.0.1", 50000)) as client:
            response = client.get("/healthz")
        assert response.headers["content-security-policy"] == f"frame-ancestors {ancestors}"
        assert response.headers.get("x-frame-options") == frame_options


def test_settings_interpolation_refuses_an_emptied_variable(monkeypatch) -> None:
    """``${VAR:-default}`` obeys the same three-state rule as ``setting_or_default``.

    Resolving an emptied variable to the empty string was a two-state collapse in the loader,
    where no scan of adapter call sites would find it: it made ``${VAR:-http://audit:8080}``
    with ``VAR=""`` indistinguishable from ``${VAR:-}``, and for a base URL, an allowlist or a
    path the empty string is the permissive branch. Absent still takes the written default.
    """
    monkeypatch.delenv("COMPLAINTS_TEST_TOKEN", raising=False)
    assert _interpolate("${COMPLAINTS_TEST_TOKEN:-fallback}") == "fallback"
    assert _interpolate("${COMPLAINTS_TEST_TOKEN}") == ""

    monkeypatch.setenv("COMPLAINTS_TEST_TOKEN", "real")
    assert _interpolate({"a": ["${COMPLAINTS_TEST_TOKEN:-fallback}"]}) == {"a": ["real"]}

    monkeypatch.setenv("COMPLAINTS_TEST_TOKEN", "  ")
    with pytest.raises(ConfiguredEmptyError):
        _interpolate("${COMPLAINTS_TEST_TOKEN:-fallback}")
    with pytest.raises(ConfiguredEmptyError):
        _interpolate("${COMPLAINTS_TEST_TOKEN}")
