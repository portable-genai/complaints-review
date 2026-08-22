"""DocumentExtractionPort — structured extraction from a complaint file.

Primary GCP adapter: **Document AI** on the Gemini Enterprise Agent Platform, pinned
to a single in-country region. It turns a raw complaint document (a letter, a form, a
statement, a screenshot of an app conversation) into a :class:`DocumentExtract` of form
fields plus full text. On-prem migration swaps this for a placeholder adapter with no
change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import DocumentExtract


@runtime_checkable
class DocumentExtractionPort(Protocol):
    def extract(self, document_id: str, content: bytes, mime_type: str) -> DocumentExtract:
        """Extract structured fields and text from a complaint document's bytes."""
        ...
