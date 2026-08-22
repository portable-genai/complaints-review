"""No CI gate may be governed by a hardcoded calendar date.

The defect this guards is a gate that stops gating without anyone noticing. The
supply-chain job once carried a temporary ``npm audit`` exception written as
``if [[ "$(date -u +%F)" > "2026-08-06" ]]``: before that date the job accepted an
allowlisted advisory, after it the job was supposed to fail. Nothing in the repository
told anyone when the date passed, and the expiry did not describe reality anyway -- the
finding that actually failed the gate was never on the allowlist, and the pin the
exception relied on had itself become the flagged version.

A date literal compared against ``date`` is therefore banned outright in the workflows:
either an advisory is accepted (fix it) or it is not (fail the build). Both branches of a
self-expiring conditional are a build whose behaviour changes with the wall clock rather
than with the code, and only one of the two branches is ever exercised by the run that
lands it.

The guard scans the workflow SOURCE rather than any parsed structure, because the
conditional lives inside a ``run:`` shell block, which YAML hands back as an opaque
string.
"""

from __future__ import annotations

import re
from pathlib import Path

_WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

#: A hardcoded calendar date, e.g. ``2026-08-06``.
_DATE_LITERAL = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

#: A reading of the CURRENT date/time from the shell or from GitHub's context.
_CURRENT_DATE = re.compile(r"\$\(\s*date\b|\bdate\s+-u\b|github\.event\.[a-z_]*_at\b")

#: How far from the ``date`` call a literal may sit and still be part of the same test.
_WINDOW = 3


def _workflow_files() -> list[Path]:
    return sorted(p for p in _WORKFLOWS.glob("*.y*ml") if p.is_file())


def test_workflows_exist() -> None:
    """A guard over an empty set is a guard that cannot fail. Prove there is a corpus."""
    assert _workflow_files(), f"no workflow files under {_WORKFLOWS}"


def test_no_date_literal_conditional_in_workflows() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if not _CURRENT_DATE.search(line):
                continue
            window = lines[max(0, index - _WINDOW) : index + _WINDOW + 1]
            literals = sorted({m.group(0) for text in window for m in _DATE_LITERAL.finditer(text)})
            if literals:
                offenders.append(
                    f"{path.name}:{index + 1}: current-date read compared against "
                    f"hardcoded {', '.join(literals)} -- {line.strip()}"
                )
    assert not offenders, (
        "A CI gate must not expire on a calendar date; fix the finding or fail the build:\n"
        + "\n".join(offenders)
    )
