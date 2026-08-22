"""ACL enforcement in the local FTS5 knowledge-base adapter (C2).

An adapter that ignores ``query.acl_principals`` entirely ("ACL is a no-op") lets any
caller retrieve any indexed passage. These tests pin the rule down at two levels:

* :func:`_acl_ok` : the fail-closed subset predicate (untagged == public; a tagged passage
  requires the caller to hold EVERY tag; empty principals see only untagged passages);
* ``search()`` : a ``tenant:<t>``-tagged passage reaches an in-tenant caller but NOT a
  cross-tenant one, while untagged public policy stays visible to everyone.

Deterministic, in-memory SQLite; no Google Cloud SDK.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from complaints_review.adapters.local.knowledge_base import LocalFtsKnowledgeBaseAdapter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.models import (
    Citation,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
)

_acl_ok = LocalFtsKnowledgeBaseAdapter._acl_ok


def _settings() -> Settings:
    return Settings(profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:"))


def _passage(source_id: str, text: str, acl_tags: tuple[str, ...] = ()) -> RetrievedPassage:
    return RetrievedPassage(
        text=text,
        citation=Citation(
            source_id=source_id,
            source_type=SourceType.POLICY,
            title=source_id,
            page=1,
            snippet=text[:40],
            score=0.9,
        ),
        score=0.9,
        acl_tags=acl_tags,
    )


# --------------------------------------------------------------------------- #
# _acl_ok : the fail-closed subset predicate.
# --------------------------------------------------------------------------- #
def test_acl_ok_untagged_is_public() -> None:
    # An untagged passage is visible to everyone, including a caller with no principals.
    assert _acl_ok((), ()) is True
    assert _acl_ok((), ("tenant:demo-bank",)) is True


def test_acl_ok_tagged_requires_every_tag() -> None:
    # Subset / all-of: the caller must hold EVERY tag the passage carries.
    assert _acl_ok(("tenant:demo-bank",), ("tenant:demo-bank",)) is True
    assert _acl_ok(("tenant:demo-bank",), ("tenant:other-bank",)) is False
    # Holding only one of two required tags is not enough (never a partial match).
    assert _acl_ok(("tenant:demo-bank", "complaint:CMP-1"), ("tenant:demo-bank",)) is False
    assert (
        _acl_ok(
            ("tenant:demo-bank", "complaint:CMP-1"),
            ("tenant:demo-bank", "complaint:CMP-1", "group:x"),
        )
        is True
    )


def test_acl_ok_empty_principals_denies_tagged() -> None:
    # Fail-closed: a caller with no principals cannot see any tagged passage.
    assert _acl_ok(("tenant:demo-bank",), ()) is False


# --------------------------------------------------------------------------- #
# search() : tenant-tagged evidence is partitioned by tenant.
# --------------------------------------------------------------------------- #
def _seeded_adapter() -> LocalFtsKnowledgeBaseAdapter:
    adapter = LocalFtsKnowledgeBaseAdapter(_settings())
    adapter.seed(
        [
            _passage("public-policy", "general complaint handling policy for all customers"),
            _passage(
                "demo-internal",
                "demo-bank internal complaint handling remediation for customers",
                acl_tags=("tenant:demo-bank",),
            ),
        ]
    )
    return adapter


def test_search_returns_tagged_passage_to_in_tenant_caller() -> None:
    adapter = _seeded_adapter()
    hits = adapter.search(
        RetrievalQuery(
            text="complaint handling customers", top_k=10, acl_principals=("tenant:demo-bank",)
        )
    )
    ids = {p.citation.source_id for p in hits}
    assert "public-policy" in ids
    assert "demo-internal" in ids


def test_search_hides_tagged_passage_from_cross_tenant_caller() -> None:
    adapter = _seeded_adapter()
    hits = adapter.search(
        RetrievalQuery(
            text="complaint handling customers", top_k=10, acl_principals=("tenant:other-bank",)
        )
    )
    ids = {p.citation.source_id for p in hits}
    assert "public-policy" in ids  # untagged public policy still grounds everyone
    assert "demo-internal" not in ids  # cross-tenant tagged evidence is invisible


def test_search_no_principals_sees_only_public() -> None:
    adapter = _seeded_adapter()
    hits = adapter.search(
        RetrievalQuery(text="complaint handling customers", top_k=10, acl_principals=())
    )
    ids = {p.citation.source_id for p in hits}
    assert ids == {"public-policy"}


def test_search_roundtrips_acl_tags_through_the_index() -> None:
    # The acl_tags column survives insert -> row -> RetrievedPassage (join/split on U+001F).
    adapter = _seeded_adapter()
    hits = adapter.search(
        RetrievalQuery(
            text="complaint handling customers", top_k=10, acl_principals=("tenant:demo-bank",)
        )
    )
    tagged = next(p for p in hits if p.citation.source_id == "demo-internal")
    assert tagged.acl_tags == ("tenant:demo-bank",)


# --------------------------------------------------------------------------- #
# Schema migration: a persistent index created BEFORE the acl_tags column upgrades
# transparently rather than raising on the missing column. (Tests otherwise use
# ``:memory:`` DBs, which always get the current schema, so this path needs an on-disk DB.)
# --------------------------------------------------------------------------- #
def test_pre_acl_ondisk_index_is_migrated(tmp_path: Path) -> None:
    db_path = tmp_path / "old.db"
    # Simulate an on-disk index created before acl_tags existed (the shipped-before schema).
    legacy = sqlite3.connect(db_path)
    legacy.execute(
        "CREATE VIRTUAL TABLE passages USING fts5("
        "text, source_id UNINDEXED, source_type UNINDEXED, title UNINDEXED, "
        "url UNINDEXED, page UNINDEXED, snippet UNINDEXED, score UNINDEXED)"
    )
    legacy.execute(
        "INSERT INTO passages (text, source_id, source_type, title, url, page, snippet, score) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("stale complaint handling clause", "OLD-1", "policy", "Old", "", "1", "stale", "0.5"),
    )
    legacy.commit()
    legacy.close()

    settings = Settings(
        profile="local", local=LocalSettings(db_path=str(db_path), audit_path=":memory:")
    )
    # Constructing the adapter migrates the schema (drop + recreate) and self-seeds; it must
    # not raise on the missing acl_tags column, and search() must answer cleanly.
    adapter = LocalFtsKnowledgeBaseAdapter(settings)
    cols = {r[1] for r in adapter._conn.execute("PRAGMA table_info(passages)")}
    assert "acl_tags" in cols

    hits = adapter.search(RetrievalQuery(text="complaint handling", top_k=5, acl_principals=()))
    assert hits, "the migrated index self-seeds, so a matching query still grounds"
    assert all(isinstance(p.acl_tags, tuple) for p in hits)
