"""Pytest fixtures: the ``local`` adapters (seeded) + assembled domain services.

The unit suite is driven by the **real** ``local`` adapter family
(``src/complaints_review/adapters/local``) rather than bespoke in-memory fakes, so the
offline implementation lives in exactly one place and the tests exercise the same code
the offline CLI runs. Every adapter constructs with a single ``Settings`` (the adapter
convention) pointed at ``:memory:`` SQLite, and the knowledge-base index is seeded with
the synthetic ``tests/fixtures/sample_complaints`` corpus for determinism.

A few fixtures wrap the local adapter in a thin **recording** subclass that captures
call arguments for assertions (``.calls`` / ``.requests`` / ``.spans`` / ``.events``).
These add no behaviour: every method delegates to the real local adapter, so the
in-memory implementation is still the one under ``adapters/local``. The recorders are
the test instrumentation the previous bespoke fakes used to bundle.

The local LLM is schema-driven (it reads ``request.response_schema`` and returns a JSON
object whose keys match it, including ``used_source_ids`` recovered from the rendered
passage headers), so it stays correct whatever field names the three services declare.
The local guardrail is the real heuristic: benign text passes, malicious text (e.g.
``sample_complaints.MALICIOUS_COMPLAINT``) is blocked, so the blocked-path tests drive
the real adapter with the appropriate input rather than a special fake.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from complaints_review.adapters.local.audit import LocalAppendOnlyAuditAdapter
from complaints_review.adapters.local.evaluation import LocalOfflineEvalAdapter
from complaints_review.adapters.local.extraction import LocalDocumentExtractionAdapter
from complaints_review.adapters.local.guardrail import LocalHeuristicGuardrailAdapter
from complaints_review.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from complaints_review.adapters.local.llm import LocalDeterministicLLMAdapter
from complaints_review.adapters.local.redaction import LocalRegexRedactionAdapter
from complaints_review.adapters.local.registry import LocalRegistryAdapter
from complaints_review.adapters.local.tool_catalog import LocalToolCatalogAdapter
from complaints_review.adapters.local.tracer import LocalNoopTracerAdapter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.models import (
    AuditEvent,
    Direction,
    DocumentExtract,
    GuardrailVerdict,
    LlmRequest,
    LlmResponse,
    RetrievalQuery,
    RetrievedPassage,
)
from tests.fixtures import sample_complaints


def _settings() -> Settings:
    """Settings whose local stores are ephemeral in-memory SQLite (deterministic)."""
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


# --------------------------------------------------------------------------- #
# Recording wrappers : thin subclasses of the local adapters that capture call
# arguments for assertions. Every method delegates to the real local adapter.
# --------------------------------------------------------------------------- #
class RecordingExtraction(LocalDocumentExtractionAdapter):
    """Local document extraction that records the document ids it was asked to extract."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []

    def extract(self, document_id: str, content: bytes, mime_type: str) -> DocumentExtract:
        self.calls.append(document_id)
        return super().extract(document_id, content, mime_type)


class RecordingKnowledgeBase(LocalFtsKnowledgeBaseAdapter):
    """Local FTS5 knowledge base that records the queries it received.

    The seeded corpus mirrors ``sample_complaints.SAMPLE_PASSAGES`` (the same source ids
    and pages). Pass ``passages=[]`` to simulate an empty governed store.
    """

    def __init__(self, settings: Settings, passages: list[RetrievedPassage] | None = None) -> None:
        super().__init__(settings)
        self.seed(list(sample_complaints.SAMPLE_PASSAGES) if passages is None else list(passages))
        self.calls: list[RetrievalQuery] = []
        # The ACL-filtered results returned per search, so tests can assert a tenant-tagged
        # passage reaches an in-tenant caller but not a cross-tenant one.
        self.results: list[list[RetrievedPassage]] = []

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        self.calls.append(query)
        out = super().search(query)
        self.results.append(list(out))
        return out


class RecordingLLM(LocalDeterministicLLMAdapter):
    """Local deterministic LLM that records the requests it received."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.requests: list[LlmRequest] = []
        self.classify_calls: list[tuple[str, list[str]]] = []

    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        return super().generate(request)

    def classify(self, text: str, labels: list[str]) -> str:
        self.classify_calls.append((text, labels))
        return super().classify(text, labels)


class RecordingGuardrail(LocalHeuristicGuardrailAdapter):
    """Local heuristic guardrail that records the (text, direction) screen calls.

    Behaviour is the real heuristic: benign text passes, malicious text (e.g.
    ``sample_complaints.MALICIOUS_COMPLAINT``) is blocked. Only the recording is added.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[tuple[str, Direction]] = []

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        self.calls.append((text, direction))
        return super().screen(text, direction)


class RecordingRedaction(LocalRegexRedactionAdapter):
    """Local regex redaction that records the raw text it was asked to redact."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.calls: list[str] = []

    def redact(self, text: str):  # type: ignore[no-untyped-def]
        self.calls.append(text)
        return super().redact(text)


class RecordingTracer(LocalNoopTracerAdapter):
    """Local no-op tracer that records the span names it opened."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.spans: list[str] = []

    def span(self, name: str, **attributes: str):  # type: ignore[no-untyped-def]
        self.spans.append(name)
        return super().span(name, **attributes)


class RecordingAudit(LocalAppendOnlyAuditAdapter):
    """Local append-only audit that also keeps the AuditEvent objects for assertions."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> None:
        self.events.append(event)
        super().record(event)


# --------------------------------------------------------------------------- #
# Backwards-compatible constructors for the unit tests that import the old fake
# names. Behaviour now comes from the real local adapters (deduped), constructed with
# the in-memory Settings; only the call recording is added on top.
# --------------------------------------------------------------------------- #
def FakeExtraction() -> RecordingExtraction:  # noqa: N802 - preserve the historic name
    return RecordingExtraction(_settings())


def FakeKnowledgeBase(  # noqa: N802 - preserve the historic name
    passages: list[RetrievedPassage] | None = None,
) -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings(), passages=passages)


def FakeLLM() -> RecordingLLM:  # noqa: N802 - preserve the historic name
    return RecordingLLM(_settings())


class BlockingGuardrail(RecordingGuardrail):
    """A guardrail that blocks via the real heuristic, used for the blocked-path tests.

    Kept as a named class (rather than a bespoke fake) so the existing tests can
    construct it directly. ``block_input`` / ``block_output`` are accepted for signature
    compatibility but blocking is driven by the real heuristic on the text it screens:
    feed it malicious text (``MALICIOUS_COMPLAINT``) and the INPUT screen blocks
    deterministically, exactly as the managed Model Armor guardrail would.
    """

    def __init__(
        self, settings: Settings | None = None, block_input: bool = True, block_output: bool = False
    ) -> None:
        super().__init__(settings or _settings())


# --------------------------------------------------------------------------- #
# Service construction : locate the domain service classes wherever they live.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "complaints_review.domain.review_service",
    "complaints_review.domain.categorization_service",
    "complaints_review.domain.response_drafting_service",
    "complaints_review.domain.services",
)
_POLICY_MODULE_CANDIDATES = (
    "complaints_review.domain.review_policy",
    "complaints_review.domain.policies",
    "complaints_review.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


def load_policy(name: str) -> Any:
    return _resolve(name, _POLICY_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures : construct the (seeded) local adapters.
# --------------------------------------------------------------------------- #
@pytest.fixture
def extraction() -> RecordingExtraction:
    return RecordingExtraction(_settings())


@pytest.fixture
def knowledge_base() -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings())


@pytest.fixture
def empty_knowledge_base() -> RecordingKnowledgeBase:
    return RecordingKnowledgeBase(_settings(), passages=[])


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM(_settings())


@pytest.fixture
def guardrail() -> RecordingGuardrail:
    return RecordingGuardrail(_settings())


@pytest.fixture
def blocking_guardrail() -> BlockingGuardrail:
    return BlockingGuardrail(_settings())


@pytest.fixture
def redaction() -> RecordingRedaction:
    return RecordingRedaction(_settings())


@pytest.fixture
def tracer() -> RecordingTracer:
    return RecordingTracer(_settings())


@pytest.fixture
def audit() -> RecordingAudit:
    return RecordingAudit(_settings())


@pytest.fixture
def evaluation() -> LocalOfflineEvalAdapter:
    return LocalOfflineEvalAdapter(_settings())


@pytest.fixture
def registry() -> LocalRegistryAdapter:
    return LocalRegistryAdapter(_settings())


@pytest.fixture
def tool_catalog() -> LocalToolCatalogAdapter:
    return LocalToolCatalogAdapter(_settings())


# Direction is re-exported for unit tests that import it from the conftest namespace.
__all__ = ["Direction"]


@pytest.fixture
def review_service(extraction, knowledge_base, llm, guardrail, redaction, tracer, audit):
    """Assemble the ComplaintReviewService from the local adapter fixtures."""
    cls = load_service("ComplaintReviewService")
    return cls(extraction, knowledge_base, llm, guardrail, redaction, tracer, audit)
