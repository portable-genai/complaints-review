"""Concurrency regression tests for the local SQLite-backed adapters.

The API serves sync ``def`` endpoints from Starlette's threadpool while
``api/deps.get_container`` is ``@lru_cache`` (one process-wide container, hence one
process-wide SQLite connection). A request handled on a different worker thread therefore
calls ``record()`` / ``search()`` on a connection opened in another thread. Without
``check_same_thread=False`` plus a lock serialising access, sqlite3 raises
"SQLite objects created in a thread can only be used in that same thread", dropping the
WORM audit record or 500-ing the retrieval under concurrent ``serve``.

These tests construct each adapter ONCE (mirroring the cached container) and drive
writes + reads from many threads via :class:`~concurrent.futures.ThreadPoolExecutor`,
asserting no exception escapes and the final row count is exactly right. They fail before
the ``check_same_thread=False`` + lock fix and pass after.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from complaints_review.adapters.local.audit import LocalAppendOnlyAuditAdapter
from complaints_review.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.models import (
    AuditEvent,
    Citation,
    Decision,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)


def _settings() -> Settings:
    """Settings whose local stores are ephemeral in-memory SQLite (one shared connection)."""
    return Settings(
        profile="local",
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


def _event(i: int) -> AuditEvent:
    return AuditEvent(
        action="review",
        actor=f"officer-{i}",
        decision=Decision.ESCALATED,
        redacted_prompt="[redacted]",
        redacted_response="[redacted]",
    )


def test_audit_adapter_is_thread_safe() -> None:
    """record()/read_all() from many threads on one connection: no error, exact count."""
    adapter = LocalAppendOnlyAuditAdapter(_settings())
    n = 200

    def work(i: int) -> int:
        adapter.record(_event(i))
        # Interleave a read so the lock guards both directions on the shared connection.
        return len(adapter.read_all())

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(work, range(n)))

    # No exception escaped (the map above would have re-raised), and every write landed.
    assert all(r >= 1 for r in results)
    assert len(adapter.read_all()) == n


def _passage(i: int) -> RetrievedPassage:
    return RetrievedPassage(
        text=f"complaint handling clause number {i} on fair treatment",
        citation=Citation(
            source_id=f"POL-{i}",
            source_type=SourceType.POLICY,
            title=f"Policy {i}",
            page=i,
            snippet="fair treatment",
            score=float(i),
        ),
        score=float(i),
    )


def test_knowledge_base_adapter_is_thread_safe() -> None:
    """add()/search() from many threads on one connection: no error, exact final count."""
    adapter = LocalFtsKnowledgeBaseAdapter(_settings())
    # Deterministic baseline: clear the self-seeded corpus so the count assertion is exact.
    adapter.seed([])
    n = 200

    def work(i: int) -> int:
        adapter.add([_passage(i)])
        # Concurrent read on the same connection alongside the writes.
        adapter.search(RetrievalQuery(text="fair treatment clause", top_k=5))
        return i

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(work, range(n)))

    hits = adapter.search(RetrievalQuery(text="fair treatment clause", top_k=10_000))
    assert len(hits) == n
