"""The remote guardrail client allows ONLY on a literal JSON ``true``.

The gateway answers with JSON. The mapping this replaced read ``bool(body.get("allowed"))``,
so the string ``"false"``, a non-zero number, or any non-empty list or object was an ALLOW.
A malformed or hostile body must fail closed: anything that is not the boolean ``true`` blocks.
"""

from __future__ import annotations

from typing import Any

import pytest

from complaints_review.adapters.platform.remote_guardrail import RemoteGuardrailAdapter
from complaints_review.domain.models import Direction

TEXT = "The bank charged me a late fee twice on the same card statement."


def _parse(body: dict[str, Any]) -> Any:
    return RemoteGuardrailAdapter._parse_verdict(body, Direction.INPUT)


def test_literal_true_allows() -> None:
    verdict = _parse({"allowed": True, "sanitized_text": TEXT, "reason": "ok"})
    assert verdict.allowed is True
    assert verdict.sanitized_text == TEXT


@pytest.mark.parametrize(
    "value",
    [False, "false", "true", "False", "0", "no", 1, 1.0, [True], {"allowed": True}, None],
    ids=repr,
)
def test_anything_but_literal_true_blocks(value: Any) -> None:
    verdict = _parse({"allowed": value, "sanitized_text": TEXT})
    assert verdict.allowed is False


def test_missing_allowed_blocks() -> None:
    assert _parse({"sanitized_text": TEXT}).allowed is False
