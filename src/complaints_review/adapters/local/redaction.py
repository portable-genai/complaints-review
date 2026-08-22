"""Local PII redaction adapter (PIIRedactionPort): regex de-identification.

The ``local`` profile's stand-in for **Sensitive Data Protection / DLP**: masks the customer
identifiers a complaint file carries (Singapore NRIC/FIN, Hong Kong HKID, Japan My Number,
Australia TFN, plus universal email and phone) with deterministic, checksum-gated regexes,
returning findings. Complaint files carry customer PII, so R1 runs this before any model call,
knowledge-base query, trace span or audit write. There is no Google emulator for DLP, so this
path is unconditional and imports no google-cloud package.

The rows and their checksum validators come from the shared ``pii-kit`` package, NOT a local
copy: this redactor, the DLP adapter and the eval leak-check all read the SAME rows, so a
pattern fix is a version bump rather than a copy that drifts out of sync. Which jurisdictions to
mask is configured in :class:`PiiSettings`; B6's default is APAC (SG/HK/JP/AU).

B6 has no bank-account row: a complaint narrative's PII is the customer's identity, not an
account number, so there is no bare-digit catch-all here and therefore no row-ordering hazard.
The universal email/phone rows lead, then the national-id rows; each match is masked only when
its validator (where present) confirms a genuine identifier.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for
from pii_kit.patterns import Pattern

from ...config import Settings
from ...domain.models import RedactionFinding, RedactionResult


class LocalRegexRedactionAdapter:
    """Mask configured-jurisdiction national ids plus email/phone, like DLP de-identify."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Universal rows first, then the national-id rows for the configured jurisdictions.
        # B6 has no account row, so this order carries no subsumption hazard.
        self._rows: tuple[Pattern, ...] = (
            *UNIVERSAL_PATTERNS,
            *tuple(national_patterns_for(settings.pii.jurisdictions)),
        )

    def redact(self, text: str) -> RedactionResult:
        redacted = text
        counts: dict[str, int] = {}
        for info_type, pattern, validator in self._rows:

            def _sub(
                m: re.Match[str],
                _it: str = info_type,
                _val: Callable[[str], bool] | None = validator,
            ) -> str:
                if _val is not None and not _val(m.group(0)):
                    return m.group(0)  # checksum fail: not a real identifier, leave it
                counts[_it] = counts.get(_it, 0) + 1
                return f"[{_it}]"

            redacted = pattern.sub(_sub, redacted)
        findings = tuple(RedactionFinding(info_type=it, count=n) for it, n in counts.items() if n)
        return RedactionResult(text=redacted, findings=findings)
