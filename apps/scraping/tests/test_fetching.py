"""fetching pipeline tests — network calls replaced by fake responses (no sockets)."""

from typing import Any
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from apps.scraping import robots
from apps.scraping.exceptions import (
    FetchBlocked,
    FetchDomainBlocked,
    FetchError,
    FetchNotFound,
    FetchRobotsDisallowed,
    FetchServerError,
    FetchTooLarge,
)
from apps.scraping.fetching import FetchMode, fetch, fetch_with_escalation, head_ok


class _CssList(list[Any]):
    def get(self, default: Any = None) -> Any:
        return self[0] if self else default


class FakeAnchor:
    def __init__(self, href: str, text: str) -> None:
        self.attrib = {"href": href}
        self._text = text

    def get_all_text(self, strip: bool = True) -> str:
        return self._text


class FakeResponse:
    def __init__(
        self,
        url: str,
        status: int = 200,
        body: str | bytes = "",
        encoding: str = "utf-8",
        anchors: list[FakeAnchor] | None = None,
        text: str = "",
    ) -> None:
        self.url = url
        self.status = status
        self.body = body.encode(encoding) if isinstance(body, str) else body
        self.encoding = encoding
        self.anchors = anchors or []
        self.text = text

    def css(self, sel: str) -> _CssList:
        if sel == "a":
            return _CssList(self.anchors)
        return _CssList()

    def get_all_text(self, strip: bool = True) -> str:
        return self.text


def _many_anchors() -> list[FakeAnchor]:
    return [FakeAnchor(f"https://co.example/page{i}", f"Link {i}") for i in range(12)]


def _rich_response(url: str = "https://co.example/careers") -> FakeResponse:
    html = (
        "<title>Careers</title>"
        + "".join(f'<a href="https://co.example/page{i}">Link {i}</a>' for i in range(12))
        + ("<p>job" * 200)
    )
    return FakeResponse(url=url, body=html, anchors=_many_anchors(), text="job " * 1200)


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
class FetchTests(SimpleTestCase):
    def test_fetch_ok_maps_response(self) -> None:
        with patch("apps.scraping.fetching._http_get", return_value=_rich_response()):
            result = fetch("https://co.example/careers")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.fetcher_used, FetchMode.HTTP)
        self.assertTrue(result.html.startswith("<title>"))
        self.assertEqual(len(result.links()), 12)

    def test_fetch_normalizes_and_throttles(self) -> None:
        slot = MagicMock()
        http = MagicMock(return_value=_rich_response("https://co.example/careers"))
        with (
            patch("apps.scraping.fetching._http_get", http),
            patch("apps.scraping.fetching.acquire_slot", slot),
        ):
            fetch("Co.Example/careers?utm_source=x#top", mode=FetchMode.HTTP)
        called_url = http.call_args.args[0]
        self.assertTrue(called_url.startswith("https://co.example/careers"))
        slot.assert_called_once()
        kwargs = slot.call_args.kwargs
        self.assertEqual(kwargs["rate_per_minute"], 100)
        self.assertEqual(kwargs["jitter_ms"], (200, 900))

    def test_blocked_domain_rejected_before_network(self) -> None:
        http = MagicMock(side_effect=AssertionError("must not hit network"))
        with patch("apps.scraping.fetching._http_get", http), self.assertRaises(FetchDomainBlocked):
            fetch("https://jobs.linkedin.com/xyz")

    def test_status_mapping(self) -> None:
        cases = [
            (404, FetchNotFound),
            (410, FetchNotFound),
            (403, FetchBlocked),
            (429, FetchBlocked),
            (503, FetchServerError),
        ]
        for status, exc in cases:
            with (
                patch(
                    "apps.scraping.fetching._http_get",
                    return_value=FakeResponse("https://co.example/x", status=status),
                ),
                self.assertRaises(exc, msg=f"status {status}"),
            ):
                fetch("https://co.example/x")

    def test_redirect_to_blocked_domain_rejected(self) -> None:
        def _get(url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(url="https://linkedin.com/trap", status=200, body="<html>")

        with (
            patch("apps.scraping.fetching._http_get", side_effect=_get),
            self.assertRaises(FetchDomainBlocked),
        ):
            fetch("https://co.example/careers")

    def test_size_cap_enforced(self) -> None:
        huge = FakeResponse("https://co.example/big", body=b"x" * (4 * 1024 * 1024))
        with (
            patch("apps.scraping.fetching._http_get", return_value=huge),
            self.assertRaises(FetchTooLarge),
        ):
            fetch("https://co.example/big")

    def test_robots_disallowed_raises(self) -> None:
        with (
            override_settings(FETCH_ROBOTS_OBEY=True),
            patch.object(robots, "is_allowed", return_value=False),
            self.assertRaises(FetchRobotsDisallowed),
        ):
            fetch("https://co.example/private")

    def test_dynamic_disabled_raises(self) -> None:
        with override_settings(FETCH_ALLOW_DYNAMIC=False), self.assertRaises(FetchError):
            fetch("https://co.example/careers", mode=FetchMode.DYNAMIC)


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100, FETCH_ALLOW_DYNAMIC=True)
class EscalationTests(SimpleTestCase):
    def test_rich_page_stays_http(self) -> None:
        # A rich page must not escalate; disable dynamic here so no browser is
        # ever launched (global socket guard forbids outbound network in tests).
        with (
            override_settings(FETCH_ALLOW_DYNAMIC=False),
            patch("apps.scraping.fetching._http_get", return_value=_rich_response()),
        ):
            result = fetch_with_escalation("https://co.example/careers")
        self.assertEqual(result.fetcher_used, FetchMode.HTTP)
        self.assertEqual(result.escalation_reason, "")

    def test_spa_page_escalates_once(self) -> None:
        spa = FakeResponse(
            url="https://co.example/jobs",
            body='<html><div id="root"></div></html>',
            anchors=[],
            text="",
        )
        dynamic = _rich_response("https://co.example/jobs")
        with (
            patch("apps.scraping.fetching._http_get", return_value=spa),
            patch("apps.scraping.fetching._dynamic_get", return_value=dynamic),
        ):
            result = fetch_with_escalation("https://co.example/jobs")
        self.assertEqual(result.fetcher_used, FetchMode.DYNAMIC)
        self.assertIn("anchors", result.escalation_reason)

    def test_escalation_failure_keeps_http_copy(self) -> None:
        def boom(url: str, **kwargs: object) -> Any:
            raise TimeoutError("timed out")

        spa = FakeResponse(
            url="https://co.example/jobs", body="<html><div id=react></div>", anchors=[], text=""
        )
        with (
            patch("apps.scraping.fetching._http_get", return_value=spa),
            patch("apps.scraping.fetching._dynamic_get", side_effect=boom),
        ):
            result = fetch_with_escalation("https://co.example/jobs")
        self.assertEqual(result.fetcher_used, FetchMode.HTTP)

    def test_dynamic_disables_escalation(self) -> None:
        spa = FakeResponse(url="https://co.example/jobs", body="<div id=root>", anchors=[], text="")
        with (
            override_settings(FETCH_ALLOW_DYNAMIC=False),
            patch("apps.scraping.fetching._http_get", return_value=spa),
        ):
            result = fetch_with_escalation("https://co.example/jobs")
        self.assertEqual(result.fetcher_used, FetchMode.HTTP)
        self.assertNotEqual(result.escalation_reason, "")


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
class HeadOkTests(SimpleTestCase):
    def test_2xx_ok(self) -> None:
        with patch(
            "apps.scraping.fetching._http_get",
            return_value=FakeResponse("https://co.example/x", status=200),
        ):
            self.assertEqual(head_ok("https://co.example/x"), (True, 200))

    def test_404_not_ok(self) -> None:
        with patch(
            "apps.scraping.fetching._http_get",
            return_value=FakeResponse("https://co.example/x", status=404),
        ):
            self.assertEqual(head_ok("https://co.example/x"), (False, 404))

    def test_blocked_domain_raises(self) -> None:
        with self.assertRaises(FetchDomainBlocked):
            head_ok("https://linkedin.com/x")

    def test_timeout_not_ok_without_raising(self) -> None:
        with patch("apps.scraping.fetching._http_get", side_effect=TimeoutError("timed out")):
            self.assertEqual(head_ok("https://co.example/x"), (False, 0))
