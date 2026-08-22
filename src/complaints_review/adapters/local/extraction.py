"""Local document-extraction adapter (DocumentExtractionPort) : SDK-free parser.

The ``local`` profile's stand-in for **Document AI**: deterministic plain-text
extraction with no SDK. If ``pypdf`` is importable and the bytes look like a PDF, the
per-page text is joined and the page count recorded; otherwise the bytes are decoded as
UTF-8 text and returned as a single page. Empty content yields a deterministic canned
extract so an out-of-the-box local review (whose attached documents have no bytes) still
contributes a structured field. There is no Google emulator for Document AI, so this
path is unconditional and imports no google-cloud package.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import DocumentExtract


class LocalDocumentExtractionAdapter:
    """Parse a complaint document's bytes into a :class:`DocumentExtract`, no SDK required."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def extract(self, document_id: str, content: bytes, mime_type: str) -> DocumentExtract:
        if not content:
            # No bytes available (e.g. a referenced-but-unfetched attachment): return a
            # deterministic canned extract so the narrative-driven review still proceeds.
            return DocumentExtract(
                document_id=document_id,
                fields={"complaint_about": "structured investment product"},
                text="Attached form: customer disputes suitability of the product sold.",
                pages=1,
            )

        if self._looks_like_pdf(content, mime_type):
            pages = self._extract_pdf_pages(content)
            if pages:
                return DocumentExtract(
                    document_id=document_id,
                    fields={},
                    text="\n\n".join(pages),
                    pages=len(pages),
                )

        # Plain-text passthrough: decode as UTF-8 and treat the whole body as one page.
        text = content.decode("utf-8", errors="replace")
        return DocumentExtract(document_id=document_id, fields={}, text=text, pages=1)

    @staticmethod
    def _looks_like_pdf(content: bytes, mime_type: str) -> bool:
        if "pdf" in (mime_type or "").lower():
            return True
        return content[:5] == b"%PDF-"

    @staticmethod
    def _extract_pdf_pages(content: bytes) -> list[str]:
        """Extract per-page text via pypdf when available; empty list if it is not."""
        try:
            import io

            from pypdf import PdfReader  # type: ignore[import-not-found]
        except Exception:  # noqa: BLE001 - pypdf is optional; fall back to text decode
            return []
        try:
            reader = PdfReader(io.BytesIO(content))
            return [(page.extract_text() or "") for page in reader.pages]
        except Exception:  # noqa: BLE001 - a malformed PDF falls back to text decode
            return []
