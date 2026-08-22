"""The local audit store is hash-chained and tamper-evident (C9)."""

from __future__ import annotations

from complaints_review.adapters.local.audit import LocalAppendOnlyAuditAdapter
from complaints_review.config import LocalSettings, Settings
from complaints_review.domain.models import AuditEvent, Decision


def _event(action: str) -> AuditEvent:
    return AuditEvent(
        action=action,
        actor="eval-bot (FICTIONAL)",
        decision=Decision.ALLOWED,
        redacted_prompt="[REDACTED] example request",
        redacted_response="[REDACTED] example response",
    )


def _adapter() -> LocalAppendOnlyAuditAdapter:
    settings = Settings(profile="local", local=LocalSettings(audit_path=":memory:"))
    return LocalAppendOnlyAuditAdapter(settings)


def test_events_round_trip_and_chain_verifies() -> None:
    adapter = _adapter()
    adapter.record(_event("review"))
    adapter.record(_event("categorise"))
    events = adapter.read_all()
    assert [e["action"] for e in events] == ["review", "categorise"]
    report = adapter.verify_chain()
    assert report.ok and report.chained == 2


def test_tampering_is_detected() -> None:
    adapter = _adapter()
    adapter.record(_event("review"))
    adapter.record(_event("categorise"))
    conn = adapter._log._conn  # noqa: SLF001 - deliberate tamper simulation
    conn.execute("DROP TRIGGER IF EXISTS audit_log_no_update")
    conn.execute(
        "UPDATE audit_log SET event_json = replace(event_json, 'review', 'x') WHERE seq = 1"
    )
    conn.commit()
    assert not adapter.verify_chain().ok
