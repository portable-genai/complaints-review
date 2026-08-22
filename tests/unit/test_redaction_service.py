"""The local redactor's wiring of the shared ``pii-kit`` rows, proven per market.

The package's own tests prove the package; these prove B6's WIRING of it: that the configured
jurisdictions are actually masked, that the metric CAN go red (a no-op redactor leaks each
market's identifier), that the checksum gate is live (an invalid identifier is left intact), and
that ordinary text is untouched. This is the per-market not-falsely-green proof the C4 rollout
requires the adopting repo to re-run.
"""

from __future__ import annotations

import pytest
from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for, pack_leak, planted_leak

from complaints_review.adapters.local.redaction import LocalRegexRedactionAdapter
from complaints_review.config import PiiSettings, Settings

# One obviously-fictional identifier per market, in printed form (JP/AU carry valid check digits).
PLANTED: dict[str, str] = {
    "SG": "S1234567D",
    "HK": "A123456(3)",
    "JP": "1234 5678 9018",
    "AU": "123 456 782",
}
MARKETS = ("SG", "HK", "JP", "AU")


def _redactor(*jurisdictions: str) -> LocalRegexRedactionAdapter:
    settings = Settings(pii=PiiSettings(jurisdictions=jurisdictions or MARKETS))
    return LocalRegexRedactionAdapter(settings)


def _rows(*jurisdictions: str):  # noqa: ANN202
    return [*UNIVERSAL_PATTERNS, *national_patterns_for(jurisdictions or MARKETS)]


class TestPerMarketNotFalselyGreen:
    @pytest.mark.parametrize("market", MARKETS)
    def test_market_is_masked_and_would_leak_without_redaction(self, market: str) -> None:
        ident = PLANTED[market]
        text = f"Customer complaint. For reference, my identifier is {ident}."
        redacted = _redactor(market).redact(text).text

        # With real redaction the planted identifier is gone: the metric would be GREEN...
        assert planted_leak(redacted, [ident]) is False, f"{market}: identifier survived redaction"
        assert not pack_leak(redacted, _rows(market)), f"{market}: pack scan still finds PII"
        # ...and without redaction (the raw text) it is present: the metric CAN go RED.
        assert planted_leak(text, [ident]) is True, f"{market}: raw text unexpectedly clean"

    @pytest.mark.parametrize("market", MARKETS)
    def test_a_finding_is_reported_per_market(self, market: str) -> None:
        text = f"id {PLANTED[market]}"
        result = _redactor(market).redact(text)
        assert result.redacted, f"{market}: no redaction finding reported"


class TestChecksumGateIsLive:
    def test_invalid_my_number_is_not_masked(self) -> None:
        # A 12-digit run with a WRONG check digit is not a My Number: the checksum row must
        # leave it intact rather than mask ordinary figures.
        text = "policy number 1234 5678 9019 on file"  # last digit broken vs the valid ...9018
        redacted = _redactor("JP").redact(text).text
        assert "1234 5678 9019" in redacted

    def test_ordinary_prose_is_untouched(self) -> None:
        text = "The branch charged a fee I never agreed to and nobody called me back."
        assert _redactor().redact(text).text == text


class TestEmailAndPhoneAreUniversal:
    def test_email_masked_regardless_of_jurisdiction(self) -> None:
        redacted = _redactor("SG").redact("reach me at jane.doe@example.com").text
        assert "jane.doe@example.com" not in redacted
