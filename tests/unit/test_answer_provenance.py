"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another.

Sampling is decided per call site here too: the review's extraction and categorisation stay
pinned at ``0.0`` and the drafted response is free, which every adapter must turn into NO
temperature at all rather than ``1.0``.
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
from functools import cached_property
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
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
from complaints_review.config import (
    OFFLINE_STUB_MODEL,
    LocalSettings,
    ModelSettings,
    Settings,
)
from complaints_review.domain.categorization_service import _CATEGORIZE_SCHEMA
from complaints_review.domain.kernel import LlmMessage, LlmRequest
from complaints_review.domain.response_drafting_service import _DRAFT_SCHEMA
from complaints_review.domain.review_service import _SUMMARY_SCHEMA

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"
CONFIG_PATH = Path("config/settings.yaml")

_SETTINGS = Settings(
    profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:")
)

_REVIEW_BODY: dict[str, Any] = {
    "file": {
        "id": "CMP-PILL-0001",
        "customer_ref": "CUST-FAKE-PILL",
        "product": "credit card",
        "channel": "branch",
        "received_date": "2026-06-01",
        "documents": [],
        "narrative": "I was charged a late fee twice on my credit card and want it refunded.",
    }
}


class _SearchingLLM(RecordingLLM):
    """The local stub, plus a note that an online search tool was attached to the call."""

    def generate(self, request: LlmRequest) -> Any:
        response = super().generate(request)
        provenance.note_search()
        return response


class _Container:
    def __init__(self, llm: RecordingLLM) -> None:
        self.settings = _SETTINGS
        self.extraction = RecordingExtraction(_SETTINGS)
        self.knowledge_base = RecordingKnowledgeBase(_SETTINGS)
        self.llm = llm
        self.guardrail = RecordingGuardrail(_SETTINGS)
        self.redaction = RecordingRedaction(_SETTINGS)
        self.tracer = RecordingTracer(_SETTINGS)
        self.audit = RecordingAudit(_SETTINGS)
        self.review_router = LocalReviewRouter(_SETTINGS)

    @cached_property
    def identity(self) -> LocalPersonaIdentityAdapter:
        return LocalPersonaIdentityAdapter(_SETTINGS)


def _client(monkeypatch: pytest.MonkeyPatch, container: _Container) -> TestClient:
    # CI runs this suite with NO profile exported (`make portability`), so the test chooses one.
    monkeypatch.setenv("COMPLAINTS_PROFILE", "local")
    from complaints_review.api import deps
    from complaints_review.api.app import app

    monkeypatch.setattr(deps, "get_container", lambda: container)
    return TestClient(app, client=("127.0.0.1", 50000))


def _review(client: TestClient) -> dict[str, str]:
    response = client.post("/v1/review", json=_REVIEW_BODY)
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_a_local_review_names_the_stub_that_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    """RED without ``install_answer_provenance``: the header is absent and the pill never moves."""
    llm = RecordingLLM(_SETTINGS)
    headers = _review(_client(monkeypatch, _Container(llm)))

    assert llm.requests, "the review made no model call, so this proves nothing"
    assert headers[ANSWERED_BY] == OFFLINE_STUB_MODEL
    local = dataclasses.replace(Settings.load(CONFIG_PATH), profile="local")
    assert headers[ANSWERED_BY] == local.generator_model, "configured and answered pills disagree"
    assert SEARCH_USED not in headers


def test_a_call_that_searched_says_so_and_the_next_request_starts_fresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    searched = _review(_client(monkeypatch, _Container(_SearchingLLM(_SETTINGS))))
    assert searched[SEARCH_USED] == "true"
    assert searched[ANSWERED_BY] == OFFLINE_STUB_MODEL

    plain = _review(_client(monkeypatch, _Container(RecordingLLM(_SETTINGS))))
    assert SEARCH_USED not in plain


def test_health_answers_nothing_about_an_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/healthz`` calls no model, so it sends neither header and the pill stays configured."""
    response = _client(monkeypatch, _Container(RecordingLLM(_SETTINGS))).get("/healthz")
    assert response.status_code == 200
    assert ANSWERED_BY not in response.headers


def test_a_cross_origin_console_is_allowed_to_read_both_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This console calls the service directly, so CORS must EXPOSE the two headers.

    RED without ``expose_headers``: the browser hides them from `fetch` and the pill never moves,
    although the service sends them and every server-side assertion above stays green.
    """
    client = _client(monkeypatch, _Container(RecordingLLM(_SETTINGS)))
    response = client.post(
        "/v1/review", json=_REVIEW_BODY, headers={"Origin": "http://localhost:3000"}
    )
    assert response.status_code == 200, response.text
    exposed = {
        h.strip().lower() for h in response.headers["access-control-expose-headers"].split(",")
    }
    assert {ANSWERED_BY, SEARCH_USED} <= exposed


def test_extraction_and_categorisation_are_pinned_and_the_draft_is_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm = RecordingLLM(_SETTINGS)
    _review(_client(monkeypatch, _Container(llm)))

    by_schema = {id(r.response_schema): r.temperature for r in llm.requests}
    assert by_schema[id(_SUMMARY_SCHEMA)] == 0.0
    assert by_schema[id(_CATEGORIZE_SCHEMA)] == 0.0
    assert by_schema[id(_DRAFT_SCHEMA)] is None


def test_no_flag_can_swap_in_a_model_the_adapter_never_calls() -> None:
    """The latent false banner: ``use_hard_reasoning`` named a model the adapter never read."""
    fields = {f.name for f in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields
    assert "hard_reasoning" not in fields
    gcp = dataclasses.replace(Settings.load(CONFIG_PATH), profile="gcp")
    assert gcp.generator_model == gcp.models.reasoning


# --------------------------------------------------------------------------- #
# The Gemini adapter, through a fake `google.genai`
# --------------------------------------------------------------------------- #
class _FakeModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(text='{"body": "ok"}', usage_metadata=None)


def _fake_genai(monkeypatch: pytest.MonkeyPatch) -> _FakeModels:
    models = _FakeModels()
    types = ModuleType("google.genai.types")
    types.GenerateContentConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types.ThinkingConfig = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types.ThinkingLevel = SimpleNamespace(LOW="LOW", HIGH="HIGH")  # type: ignore[attr-defined]
    types.Content = lambda **kw: SimpleNamespace(**kw)  # type: ignore[attr-defined]
    types.Part = SimpleNamespace(from_text=lambda text: text)  # type: ignore[attr-defined]
    genai = ModuleType("google.genai")
    genai.types = types  # type: ignore[attr-defined]
    genai.Client = lambda **_: SimpleNamespace(models=models)  # type: ignore[attr-defined]
    try:
        google = importlib.import_module("google")
    except ImportError:
        google = ModuleType("google")
        google.__path__ = []
        monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setattr(google, "genai", genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)
    return models


def _request(temperature: float | None) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="hi"),), temperature=temperature)


def test_the_gemini_adapter_notes_the_model_it_called_and_omits_a_free_temperature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from complaints_review.adapters.gcp.gemini_llm import GeminiLLMAdapter

    models = _fake_genai(monkeypatch)
    gcp = dataclasses.replace(Settings.load(CONFIG_PATH), profile="gcp")
    adapter = GeminiLLMAdapter(gcp)

    with provenance.scope() as record:
        adapter.generate(_request(None))
    assert record.models == [models.calls[0]["model"]]
    assert models.calls[0]["model"] == gcp.generator_model
    assert not hasattr(models.calls[0]["config"], "temperature"), "free must mean absent"
    assert record.search_used is False, "no online search tool is attached to this call"

    adapter.generate(_request(0.0))
    assert models.calls[1]["config"].temperature == 0.0


def test_the_live_adapter_passes_a_free_temperature_through_as_none() -> None:
    from complaints_review.adapters.live.llm import LocalModelLLMAdapter

    seen: list[Any] = []

    class _Client:
        def complete(self, messages: Any, **kwargs: Any) -> Any:
            seen.append(kwargs.get("temperature", "absent"))
            return SimpleNamespace(text="ok", usage=None, model="local-model")

    LocalModelLLMAdapter(_SETTINGS, client=_Client()).generate(_request(None))  # type: ignore[arg-type]
    assert seen == [None]
