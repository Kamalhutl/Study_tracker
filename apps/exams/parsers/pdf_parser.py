import re
from typing import NamedTuple


class DateCandidate(NamedTuple):
    raw: str
    parsed: str | None  # YYYY-MM-DD if parseable
    context: str


class PdfExtractResult(NamedTuple):
    text: str
    page_count: int
    pages_extracted: int
    has_text_layer: bool
    truncated: bool
    warnings: list[str]


class PdfExtractionError(Exception):
    pass


def extract_text(
    pdf_bytes: bytes, *, source_url: str, max_bytes: int = 20 * 1024 * 1024, max_pages: int = 500
) -> PdfExtractResult:
    """
    Defensive PDF text extractor.
    Uses PyPDF2 for simplicity (pinned).
    """
    import io

    from PyPDF2 import PdfReader

    warnings = []
    if len(pdf_bytes) == 0:
        return PdfExtractResult("", 0, 0, False, False, ["Empty file"])
    if len(pdf_bytes) > max_bytes:
        warnings.append(f"File size {len(pdf_bytes)} exceeds limit {max_bytes}, refusing to parse.")
        return PdfExtractResult("", 0, 0, False, False, warnings)
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        if page_count == 0:
            return PdfExtractResult("", 0, 0, False, False, ["No pages"])
        if page_count > max_pages:
            warnings.append(
                f"Page count {page_count} exceeds max {max_pages}, truncating to {max_pages} pages."
            )
            pages_to_extract = max_pages
            truncated = True
        else:
            pages_to_extract = page_count
            truncated = False
        text_parts = []
        has_text = False
        for i in range(pages_to_extract):
            page = reader.pages[i]
            page_text = page.extract_text()
            if page_text and page_text.strip():
                has_text = True
                text_parts.append(page_text)
        full_text = "\n".join(text_parts)
        return PdfExtractResult(
            text=full_text,
            page_count=page_count,
            pages_extracted=pages_to_extract,
            has_text_layer=has_text,
            truncated=truncated,
            warnings=warnings,
        )
    except Exception as e:
        return PdfExtractResult("", 0, 0, False, False, [f"Extraction error: {e!s}"])


def find_date_candidates(text: str) -> list[DateCandidate]:
    """
    Pure function: extract date-like strings and attempt to parse them.
    Returns list of candidates with raw, parsed (YYYY-MM-DD or None), and context.
    """
    # Simple regex for dates in various formats
    patterns = [
        (r"\b\d{1,2}[-\s/]\d{1,2}[-\s/]\d{2,4}\b", "day-month-year"),
        (r"\b\d{2,4}[-\s/]\d{1,2}[-\s/]\d{1,2}\b", "year-month-day"),
        (
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
            "month-day-year",
        ),
        (
            r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b",
            "day-month-year-text",
        ),
    ]
    candidates = []
    for pat, _ in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            raw = match.group(0)
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace("\n", " ")
            parsed = None
            # Naive parsing attempt
            try:
                from dateutil import parser

                dt = parser.parse(raw, fuzzy=True)
                parsed = dt.date().isoformat()
            except Exception:
                pass
            candidates.append(DateCandidate(raw, parsed, context))
    # Deduplicate by raw
    seen = set()
    unique = []
    for c in candidates:
        if c.raw not in seen:
            seen.add(c.raw)
            unique.append(c)
    return unique
