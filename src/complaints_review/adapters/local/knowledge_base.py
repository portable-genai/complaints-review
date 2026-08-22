"""Local knowledge-base adapter (KnowledgeBaseClientPort) — SQLite FTS5 over the corpus.

The ``local`` profile's stand-in for the governed **A2 Enterprise Knowledge Base** (and
the direct **Agent Search** adapter): a ``sqlite3`` database with an **FTS5** virtual
table over the policy / regulatory passages, queried with BM25 (``ORDER BY rank``). It is
SDK-free, deterministic and **seedable**, so the same code grounds the offline CLI run
and the unit tests. There is no Google emulator for Agent Search, so this path is
unconditional (no emulator branch).

The adapter returns the same :class:`RetrievedPassage` objects with page-level
:class:`Citation` provenance as the managed adapter, preserving interface parity. It
self-seeds from the built-in synthetic corpus on first use so an out-of-the-box local
run grounds the review without any ingestion step; callers (and the tests) may also
``seed(passages)`` a corpus of their own.

Default DB path is under a per-package local dir (``~/.complaints_review/local.db``);
tests pass ``:memory:`` for an ephemeral, deterministic index.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path

from ...config import Settings
from ...domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)
from ._seed import SEED_PASSAGES

# Default on-disk location for the local index (overridable via settings.local.db_path).
_DEFAULT_DB_DIR = Path.home() / ".complaints_review"
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "local.db"

# FTS5 query syntax is strict; keep only word characters so a free-text complaint query
# never trips an "fts5: syntax error" (e.g. on punctuation), and OR the terms for recall.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
_ACL_SEP = "\x1f"  # unit-separator: joins acl_tags into one UNINDEXED column safely.

_SOURCE_TYPE_BY_VALUE: dict[str, SourceType] = {s.value: s for s in SourceType}


class LocalFtsKnowledgeBaseAdapter:
    """Retrieve grounded policy / regulatory passages from a local SQLite FTS5 index."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        db_path = getattr(getattr(settings, "local", None), "db_path", "") or str(_DEFAULT_DB_PATH)
        self._db_path = db_path
        # The API serves sync endpoints from Starlette's threadpool while the container is
        # process-wide cached, so this one connection is reused across worker threads.
        # check_same_thread=False + a reentrant lock guarding every access serialises the
        # index (single-writer) so a cross-thread query cannot raise the same-thread error.
        self._lock = threading.RLock()
        self._conn = self._connect(db_path)
        self._init_schema()
        # Self-seed the built-in corpus so an out-of-the-box local run is grounded.
        with self._lock:
            if self._is_empty():
                self.seed(SEED_PASSAGES)

    # ------------------------------------------------------------------ #
    # Connection / schema
    # ------------------------------------------------------------------ #
    @staticmethod
    def _connect(db_path: str) -> sqlite3.Connection:
        if db_path not in (":memory:", "") and not db_path.startswith("file:"):
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    #: FTS5 schema: one searchable ``text`` column; citation metadata + ACL tags ride
    #: alongside as UNINDEXED columns so a single query returns everything needed to cite
    #: and ACL-filter a hit. ``acl_tags`` was added when the C2 no-op-ACL gap was closed.
    _CREATE_SQL = """
        CREATE VIRTUAL TABLE passages USING fts5(
            text,
            source_id UNINDEXED,
            source_type UNINDEXED,
            title UNINDEXED,
            url UNINDEXED,
            page UNINDEXED,
            snippet UNINDEXED,
            score UNINDEXED,
            acl_tags UNINDEXED
        )
    """

    def _init_schema(self) -> None:
        with self._lock:
            cols = {row[1] for row in self._conn.execute("PRAGMA table_info(passages)")}
            # Migrate a pre-ACL on-disk index: a persistent DB created before the acl_tags
            # column exists as an older table that CREATE ... IF NOT EXISTS would silently
            # leave untouched, so _row_to_passage would raise on the missing column. The
            # local index self-seeds when empty, so rebuilding it is transparent and safe.
            if cols and "acl_tags" not in cols:
                self._conn.execute("DROP TABLE passages")
                cols = set()
            if not cols:
                self._conn.execute(self._CREATE_SQL)
            self._conn.commit()

    def _is_empty(self) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT count(*) AS n FROM passages").fetchone()
        return int(row["n"]) == 0

    # ------------------------------------------------------------------ #
    # Seeding / ingestion
    # ------------------------------------------------------------------ #
    def seed(self, passages: tuple[RetrievedPassage, ...] | list[RetrievedPassage]) -> int:
        """Replace the index contents with ``passages`` (deterministic test/CLI seed)."""
        with self._lock:
            self._conn.execute("DELETE FROM passages")
            return self._insert(list(passages))

    def add(self, passages: list[RetrievedPassage]) -> int:
        """Append ``passages`` to the index without clearing existing rows."""
        return self._insert(passages)

    def _insert(self, passages: list[RetrievedPassage]) -> int:
        rows = []
        for p in passages:
            c = p.citation
            rows.append(
                (
                    p.text,
                    c.source_id,
                    c.source_type.value,
                    c.title,
                    c.url,
                    "" if c.page is None else str(c.page),
                    c.snippet,
                    "" if c.score is None else f"{c.score:.6f}",
                    _ACL_SEP.join(p.acl_tags),
                )
            )
        with self._lock:
            self._conn.executemany(
                "INSERT INTO passages "
                "(text, source_id, source_type, title, url, page, snippet, score, acl_tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------------ #
    # KnowledgeBaseClientPort
    # ------------------------------------------------------------------ #
    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        """Return ranked, ACL-filtered passages with page-level citations for ``query``.

        Over-fetch from the index, then apply the fail-closed subset ACL filter so a
        governed query returns up to ``top_k`` passages the caller is entitled to see: an
        untagged passage is public; a tagged passage (e.g. ``tenant:<t>``) requires the
        caller's ``acl_principals`` to hold EVERY tag. The over-fetch keeps entitled
        passages from being starved by higher-ranked rows the caller may not read.
        """
        match = self._build_match(query.text)
        source_type = (query.filters or {}).get("source_type")
        top_k = max(query.top_k, 1)
        # Over-fetch before the ACL filter so tagged rows the caller can't see don't crowd
        # out entitled ones within the top_k window.
        limit = top_k * 4

        if not match:
            # No usable query terms: fall back to a score-ordered scan so the pipeline
            # still gets something deterministic rather than an FTS5 syntax error.
            sql = (
                "SELECT * FROM passages "
                + ("WHERE source_type = ? " if source_type else "")
                + "ORDER BY score DESC LIMIT ?"
            )
            params: list[object] = ([source_type] if source_type else []) + [limit]
        else:
            sql = (
                "SELECT * FROM passages WHERE passages MATCH ? "
                + ("AND source_type = ? " if source_type else "")
                + "ORDER BY rank LIMIT ?"
            )
            params = [match] + ([source_type] if source_type else []) + [limit]

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        out: list[RetrievedPassage] = []
        for row in rows:
            passage = self._row_to_passage(row)
            if self._acl_ok(passage.acl_tags, query.acl_principals):
                out.append(passage)
            if len(out) >= top_k:
                break
        return out

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _acl_ok(passage_tags: tuple[str, ...], acl_principals: tuple[str, ...]) -> bool:
        """A passage is visible when untagged, or when the query holds EVERY tag.

        Subset (all-of) semantics, fail-closed: a passage tagged ``tenant:<t>`` (and any
        further tags) is visible only to a query whose ``acl_principals`` contain all of
        them, so tenant-tagged evidence never crosses a tenant boundary and an empty
        principal set sees only untagged (public reference) passages. Mirrors the ACL
        contract documented on ``ports.knowledge_base.KnowledgeBaseClientPort``.
        """
        if not passage_tags:
            return True
        return set(passage_tags) <= set(acl_principals)

    @staticmethod
    def _build_match(text: str) -> str:
        """Build a safe FTS5 MATCH expression: OR of the alphanumeric query tokens."""
        tokens = _TOKEN_RE.findall(text or "")
        if not tokens:
            return ""
        # Quote each token so reserved words (AND/OR/NOT/NEAR) are treated as literals.
        return " OR ".join(f'"{t}"' for t in tokens)

    @staticmethod
    def _row_to_passage(row: sqlite3.Row) -> RetrievedPassage:
        page_raw = row["page"]
        page = int(page_raw) if page_raw not in (None, "") else None
        try:
            score = float(row["score"])
        except (TypeError, ValueError):
            score = 0.0
        citation = Citation(
            source_id=row["source_id"],
            source_type=_SOURCE_TYPE_BY_VALUE.get(row["source_type"], SourceType.POLICY),
            title=row["title"],
            url=row["url"] or "",
            page=page,
            snippet=row["snippet"] or (row["text"] or "")[:280],
            score=score,
        )
        acl_tags = tuple(t for t in (row["acl_tags"] or "").split(_ACL_SEP) if t)
        return RetrievedPassage(text=row["text"], citation=citation, score=score, acl_tags=acl_tags)
