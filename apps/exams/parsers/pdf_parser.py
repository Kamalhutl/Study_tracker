"""
PDF parser — extracted text is data, never instructions.
No caller may pass extracted text to an LLM as a prompt or execute anything derived from it.
No value produced by this module may set is_published or verified_by_human.
"""

import re
from typing import NamedTuple


class DateCandidate(NamedTuple):
    raw: str
    parsed: str | None  # YYYY-MM-DD if parseable
    context: str
    format_hint: (
        str  # e.g. "day-month-year", "year-month-day", "month-day-year", "day-month-year-text"
    )
    ambiguous: bool  # True if both day and month <= 12
    source_url: str


class PdfExtractResult(NamedTuple):
    text: str
    page_count: int
    pages_extracted: int
    has_text_layer: bool
    truncated: bool
    warnings: list[str]
    source_url: str  # provenance


def extract_text(
    pdf_bytes: bytes, *, source_url: str, max_bytes: int = 20 * 1024 * 1024, max_pages: int = 500
) -> PdfExtractResult:
    """
    Defensive PDF text extractor using pypdf.
    """
    import io

    from pypdf import PdfReader

    warnings = []
    if len(pdf_bytes) == 0:
        return PdfExtractResult("", 0, 0, False, False, ["Empty file"], source_url)
    if len(pdf_bytes) > max_bytes:
        warnings.append(f"File size {len(pdf_bytes)} exceeds limit {max_bytes}, refusing to parse.")
        return PdfExtractResult("", 0, 0, False, False, warnings, source_url)
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        page_count = len(reader.pages)
        if page_count == 0:
            return PdfExtractResult("", 0, 0, False, False, ["No pages"], source_url)
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
            source_url=source_url,
        )
    except Exception as e:
        return PdfExtractResult("", 0, 0, False, False, [f"Extraction error: {e!s}"], source_url)


def find_date_candidates(text: str, source_url: str = "") -> list[DateCandidate]:
    """
    Extract date-like strings and attempt to parse them.
    Returns list of candidates with raw, parsed (YYYY-MM-DD or None), context, format hint,
    ambiguity flag, and source URL.
    """
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
    for pat, hint in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            raw = match.group(0)
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = text[start:end].replace("\n", " ")
            parsed = None
            ambiguous = False
            # Parse with appropriate dayfirst setting
            try:
                from dateutil import parser

                # Determine dayfirst based on hint
                dayfirst = hint.startswith("day")
                # For year-month-day, dayfirst=False
                if hint == "year-month-day":
                    dayfirst = False
                dt = parser.parse(raw, fuzzy=True, dayfirst=dayfirst)
                parsed = dt.date().isoformat()
                # Determine ambiguity: if both day and month <= 12 and format is numeric ambiguous
                if hint in ("day-month-year", "year-month-day"):
                    parts = re.split(r"[-\s/]", raw)
                    if len(parts) == 3:
                        try:
                            d1, d2, d3 = int(parts[0]), int(parts[1]), int(parts[2])
                            # Ambiguous if the first two numbers are both <= 12 (i.e., could be day/month)
                            if (
                                hint == "day-month-year" and d1 <= 12 and d2 <= 12 and d1 != d2
                            ) or (hint == "year-month-day" and d2 <= 12 and d3 <= 12 and d2 != d3):
                                ambiguous = True
                        except ValueError:
                            pass
            except Exception:
                pass
            candidates.append(DateCandidate(raw, parsed, context, hint, ambiguous, source_url))
    # Deduplicate by raw, keep first occurrence (which preserves context)
    seen = set()
    unique = []
    for c in candidates:
        if c.raw not in seen:
            seen.add(c.raw)
            unique.append(c)
    return unique
