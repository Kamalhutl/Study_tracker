import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

from apps.scraping.fetching import FetchResult
from apps.scraping.parsers import ats_ashby, ats_greenhouse, ats_lever, ats_smartrecruiters
from apps.scraping.spiders import static_jobs

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    """Load a fixture file from the fixtures directory."""
    path = FIXTURE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    with open(path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def load_html_fixture(name: str) -> str:
    path = FIXTURE_DIR / f"{name}.html"
    if not path.exists():
        raise FileNotFoundError(f"HTML fixture not found: {path}")
    return path.read_text()


def load_expected(name: str) -> list[dict[str, Any]]:
    """Load the expected output for a parser."""
    path = FIXTURE_DIR / f"{name}_expected.json"
    if not path.exists():
        raise FileNotFoundError(f"Expected file not found: {path}")
    with open(path) as f:
        return json.load(f)  # type: ignore[no-any-return]


def _convert_datetimes(obj):
    """Recursively convert datetime objects to ISO format strings."""
    from datetime import datetime

    if isinstance(obj, datetime):
        return obj.isoformat()
    elif isinstance(obj, dict):
        return {k: _convert_datetimes(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_datetimes(item) for item in obj]
    else:
        return obj


class _StdlibAnchor:
    def __init__(self, href: str, text: str):
        self.attrib = {"href": href}
        self._text = text

    def get_all_text(self, strip: bool = False) -> str:
        return self._text.strip() if strip else self._text


class _StdlibSelector:
    def __init__(self, html: str):
        self._anchors: list[_StdlibAnchor] = []
        parser = _AnchorCollector(self._anchors)
        parser.feed(html)

    def css(self, selector: str) -> list[_StdlibAnchor]:
        if selector == "a":
            return self._anchors
        return []


class _AnchorCollector(HTMLParser):
    def __init__(self, out: list[_StdlibAnchor]):
        super().__init__()
        self._out = out
        self._in_a = False
        self._current_href = ""
        self._current_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self._in_a = True
            self._current_href = ""
            self._current_text_parts = []
            for name, value in attrs:
                if name == "href" and value is not None:
                    self._current_href = value

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_a:
            self._in_a = False
            text = "".join(self._current_text_parts)
            self._out.append(_StdlibAnchor(self._current_href, text))

    def handle_data(self, data: str) -> None:
        if self._in_a:
            self._current_text_parts.append(data)


@pytest.mark.parametrize(
    "parser_name,parser_module,fixture_name",
    [
        ("greenhouse", ats_greenhouse, "greenhouse"),
        ("lever", ats_lever, "lever"),
        ("ashby", ats_ashby, "ashby"),
        ("smartrecruiters", ats_smartrecruiters, "smartrecruiters"),
    ],
)
def test_golden_parser(parser_name, parser_module, fixture_name):
    """Golden-file test for each JSON-based ATS parser."""
    raw_data = load_fixture(fixture_name)

    class DummySelector:
        @staticmethod
        def json():
            return raw_data

    fetch_result = FetchResult(
        url=f"https://example.com/{fixture_name}",
        final_url=f"https://example.com/{fixture_name}",
        status_code=200,
        html="",
        selector=DummySelector(),
        fetcher_used="http",
        elapsed_ms=0,
        from_cache=False,
        escalation_reason="",
    )

    result = parser_module.parse(fetch_result, company=None)
    result = _convert_datetimes(result)
    expected = load_expected(fixture_name)
    result_sorted = sorted(result, key=lambda x: x.get("source_job_id", ""))
    expected_sorted = sorted(expected, key=lambda x: x.get("source_job_id", ""))
    assert result_sorted == expected_sorted


def test_golden_static_parser():
    html = load_html_fixture("static")
    selector = _StdlibSelector(html)

    class FakeCompany:
        career_url = "https://example.com/careers"

    fetch_result = FetchResult(
        url="https://example.com/careers",
        final_url="https://example.com/careers",
        status_code=200,
        html=html,
        selector=selector,
        fetcher_used="http",
        elapsed_ms=0,
        from_cache=False,
        escalation_reason="",
    )

    result = static_jobs.extract(fetch_result, company=FakeCompany())
    result = _convert_datetimes(result)
    expected = load_expected("static")
    result_sorted = sorted(result, key=lambda x: x.get("source_url", ""))
    expected_sorted = sorted(expected, key=lambda x: x.get("source_url", ""))
    assert result_sorted == expected_sorted
