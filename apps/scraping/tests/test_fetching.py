"""fetching pipeline tests — network calls replaced by fake responses (no sockets)."""

from typing import Any
from unittest.mock import MagicMock, Mock, patch

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
from apps.scraping.fetching import (
    FetchMode,
    FetchResult,
    _blocked_host,
    _classify,
    _dynamic_get,
    _http_get,
    _proxy_for,
    _stealth_get,
    _to_fetch_result,
    _user_agent,
    fetch,
    fetch_robots_raw,
    fetch_with_escalation,
    head_ok,
    session_for,
)


class _CssList(list[Any]):
    def get(self, default: Any = None) -> Any:
        return self[0] if self else default


class FakeAnchor:
    def __init__(self, href: str, text: str) -> None:
        self.attrib = {"href": href}
        self._text = text

    def get_all_text(self, strip: bool = True) -> str:
        return self._text


class FakeScript:
    def __init__(self, raw: str) -> None:
        self._raw = raw

    def get_all_text(self, ignore_tags: list[Any] | None = None) -> str:
        return self._raw


class FakeResponse:
    def __init__(
        self,
        url: str,
        status: int = 200,
        body: str | bytes = "",
        encoding: str = "utf-8",
        anchors: list[FakeAnchor] | None = None,
        text: str = "",
        scripts: list[FakeScript] | None = None,
    ) -> None:
        self.url = url
        self.status = status
        self.body = body.encode(encoding) if isinstance(body, str) else body
        self.encoding = encoding
        self.Anchors = anchors or []
        self.text = text
        self.Scripts = scripts or []

    def css(self, sel: str) -> _CssList:
        if sel == "a" or sel.endswith(" a") or " a " in sel:
            return _CssList(self.Anchors)
        if sel == "title::text":
            return _CssList()
        if sel == 'meta[property="og:title"]::attr(content)':
            return _CssList()
        if sel == 'script[type="application/ld+json"]':
            return _CssList(self.Scripts)
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
        huge = FakeResponse("https://co.example/big", body=b"x" * 2048)
        with (
            override_settings(FETCH_MAX_RESPONSE_BYTES=1024),
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


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
class FetchResultTests(SimpleTestCase):
    """Tests for FetchResult methods: links, title, text, json_ld, region_links, _abs."""

    def _make_result(self, body: str = "", anchors=None, text: str = "") -> FetchResult:
        resp = FakeResponse(
            url="https://co.example/page",
            body=body,
            anchors=anchors or [],
            text=text,
        )
        return FetchResult(
            url="https://co.example/page",
            final_url="https://co.example/page",
            status_code=200,
            html=body,
            selector=resp,
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=10,
            from_cache=False,
            escalation_reason="",
        )

    def test_blocked_host_empty_url(self) -> None:
        self.assertFalse(_blocked_host(""))

    def test_abs_empty_href(self) -> None:
        result = self._make_result()
        self.assertIsNone(result._abs(""))

    def test_abs_special_protocols(self) -> None:
        result = self._make_result()
        for href in (
            "#anchor",
            "mailto:x@y.com",
            "tel:+1234",
            "javascript:void(0)",
            "data:text/html,xxx",
        ):
            self.assertIsNone(result._abs(href))

    def test_abs_normal_href(self) -> None:
        result = self._make_result()
        self.assertEqual(result._abs("/page2"), "https://co.example/page2")

    def test_links_skipsNoneHref(self) -> None:
        anchor = FakeAnchor("", "empty")
        result = self._make_result(anchors=[anchor])
        self.assertEqual(result.links(), [])

    def test_links_dedupes(self) -> None:
        anchors = [
            FakeAnchor("https://co.example/a", "A"),
            FakeAnchor("https://co.example/a", "A2"),
        ]
        result = self._make_result(anchors=anchors)
        self.assertEqual(len(result.links()), 1)

    def test_title_from_title_tag(self) -> None:
        class _TitleResponse(FakeResponse):
            def css(self, sel: str) -> _CssList:
                if sel == "title::text":
                    return _CssList(["Jobs"])
                return super().css(sel)

        resp = _TitleResponse(url="https://co.example/x", body="<title>Jobs</title>")
        result = FetchResult(
            url="https://co.example/x",
            final_url="https://co.example/x",
            status_code=200,
            html="<title>Jobs</title>",
            selector=resp,
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=5,
            from_cache=False,
            escalation_reason="",
        )
        self.assertEqual(result.title(), "Jobs")

    def test_title_empty_when_no_title(self) -> None:
        result = self._make_result()
        self.assertEqual(result.title(), "")

    def test_text_extraction(self) -> None:
        result = self._make_result(text="hello world")
        self.assertEqual(result.text(), "hello world")

    def test_json_ld_list(self) -> None:
        class _Script:
            def __init__(self, raw: str) -> None:
                self._raw = raw

            def get_all_text(self, ignore_tags: list[Any] | None = None) -> str:
                return self._raw

        class _JsonLdResponse(FakeResponse):
            def __init__(self, scripts: list[str]) -> None:
                super().__init__(url="https://co.example/x", body="")
                self._scripts = [_Script(s) for s in scripts]

            def css(self, sel: str) -> _CssList:
                if sel == 'script[type="application/ld+json"]':
                    return _CssList(self._scripts)
                return super().css(sel)

        resp = _JsonLdResponse(['[{"@type": "JobPosting", "title": "Dev"}]'])
        result = FetchResult(
            url="https://co.example/x",
            final_url="https://co.example/x",
            status_code=200,
            html="",
            selector=resp,
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=5,
            from_cache=False,
            escalation_reason="",
        )
        blocks = result.json_ld()
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["title"], "Dev")

    def test_json_ld_single_dict(self) -> None:
        class _Script:
            def get_all_text(self, ignore_tags: list[Any] | None = None) -> str:
                return '{"@type": "Organization"}'

        class _JsonLdResponse(FakeResponse):
            def __init__(self) -> None:
                super().__init__(url="https://co.example/x", body="")

            def css(self, sel: str) -> _CssList:
                if sel == 'script[type="application/ld+json"]':
                    return _CssList([_Script()])
                return super().css(sel)

        resp = _JsonLdResponse()
        result = FetchResult(
            url="https://co.example/x",
            final_url="https://co.example/x",
            status_code=200,
            html="",
            selector=resp,
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=5,
            from_cache=False,
            escalation_reason="",
        )
        blocks = result.json_ld()
        self.assertEqual(len(blocks), 1)

    def test_json_ld_malformed_skipped(self) -> None:
        class _Script:
            def get_all_text(self, ignore_tags: list[Any] | None = None) -> str:
                return "not json"

        class _JsonLdResponse(FakeResponse):
            def __init__(self) -> None:
                super().__init__(url="https://co.example/x", body="")

            def css(self, sel: str) -> _CssList:
                if sel == 'script[type="application/ld+json"]':
                    return _CssList([_Script()])
                return super().css(sel)

        resp = _JsonLdResponse()
        result = FetchResult(
            url="https://co.example/x",
            final_url="https://co.example/x",
            status_code=200,
            html="",
            selector=resp,
            fetcher_used=FetchMode.HTTP,
            elapsed_ms=5,
            from_cache=False,
            escalation_reason="",
        )
        self.assertEqual(result.json_ld(), [])

    def test_region_links_header(self) -> None:
        anchors = [FakeAnchor("https://co.example/h1", "Header Link")]
        result = self._make_result(anchors=anchors)
        links = result.region_links("header")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][1], "Header Link")

    def test_region_links_nav(self) -> None:
        anchors = [FakeAnchor("https://co.example/n1", "Nav Link")]
        result = self._make_result(anchors=anchors)
        links = result.region_links("nav")
        self.assertEqual(len(links), 1)

    def test_region_links_footer(self) -> None:
        anchors = [FakeAnchor("https://co.example/f1", "Footer Link")]
        result = self._make_result(anchors=anchors)
        links = result.region_links("footer")
        self.assertEqual(len(links), 1)

    def test_region_links_invalid_region(self) -> None:
        anchors = [FakeAnchor("https://co.example/x1", "Link")]
        result = self._make_result(anchors=anchors)
        links = result.region_links("invalid")
        self.assertEqual(len(links), 1)


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
class HelperFunctionTests(SimpleTestCase):
    """Tests for internal helper functions _classify, _user_agent, _proxy_for, etc."""

    def test_classify_passthrough_fetch_error(self) -> None:
        err = FetchError("original", url="https://co.example/x")
        result = _classify(err, "https://co.example/x")
        self.assertIs(result, err)

    def test_classify_timeout(self) -> None:
        err = TimeoutError("Request timed out")
        result = _classify(err, "https://co.example/x")
        from apps.scraping.exceptions import FetchTimeout

        self.assertIsInstance(result, FetchTimeout)

    def test_classify_generic_error(self) -> None:
        err = RuntimeError("something broke")
        result = _classify(err, "https://co.example/x")
        self.assertIsInstance(result, FetchError)
        self.assertIn("something broke", str(result))

    def test_user_agent(self) -> None:
        ua = _user_agent()
        self.assertIsInstance(ua, str)
        self.assertTrue(len(ua) > 0)

    @override_settings(FETCH_PROXY="")
    def test_proxy_for_empty(self) -> None:
        self.assertEqual(_proxy_for(), {})

    @override_settings(FETCH_PROXY="http://proxy.example:8080")
    def test_proxy_for_http(self) -> None:
        proxies = _proxy_for()
        self.assertEqual(proxies["http"], "http://proxy.example:8080")

    @override_settings(FETCH_PROXY="proxy.example:8080")
    def test_proxy_for_no_scheme(self) -> None:
        proxies = _proxy_for()
        self.assertEqual(proxies["http"], "http://proxy.example:8080")

    @patch("apps.scraping.fetching.Fetcher.get")
    def test_http_get_get_method(self, mock_get: Mock) -> None:
        mock_get.return_value = FakeResponse("https://co.example/x")
        _http_get("https://co.example/x", timeout=10, method="GET")
        mock_get.assert_called_once()

    @patch("apps.scraping.fetching.Fetcher.get")
    def test_http_get_head_method_raises(self, mock_get: Mock) -> None:
        with self.assertRaises(FetchError):
            _http_get("https://co.example/x", timeout=10, method="HEAD")
        mock_get.assert_not_called()

    @patch("apps.scraping.fetching.Fetcher.get")
    def test_http_get_unsupported_method(self, mock_get: Mock) -> None:
        with self.assertRaises(FetchError):
            _http_get("https://co.example/x", timeout=10, method="PUT")
        mock_get.assert_not_called()

    @override_settings(FETCH_ALLOW_DYNAMIC=True)
    @patch("apps.scraping.fetching.DynamicFetcher.fetch")
    def test_dynamic_get(self, mock_fetch: Mock) -> None:
        mock_fetch.return_value = FakeResponse("https://co.example/x")
        _dynamic_get("https://co.example/x", timeout=10, xhr_pattern="api")
        mock_fetch.assert_called_once()

    @override_settings(FETCH_ALLOW_STEALTHY=True)
    @patch("apps.scraping.fetching.StealthyFetcher.fetch")
    def test_stealth_get(self, mock_fetch: Mock) -> None:
        mock_fetch.return_value = FakeResponse("https://co.example/x")
        _stealth_get("https://co.example/x", timeout=10)
        mock_fetch.assert_called_once()

    def test_to_fetch_result_encoding(self) -> None:
        resp = FakeResponse("https://co.example/x", body="hello", encoding="utf-8")
        result = _to_fetch_result("https://co.example/x", resp, FetchMode.HTTP, 50)
        self.assertEqual(result.html, "hello")
        self.assertEqual(result.elapsed_ms, 50)
        self.assertFalse(result.from_cache)

    def test_to_fetch_result_missing_encoding(self) -> None:
        resp = FakeResponse("https://co.example/x", body="hello")
        resp.encoding = ""  # falsy triggers the `or "utf-8"` fallback
        result = _to_fetch_result("https://co.example/x", resp, FetchMode.HTTP, 50)
        self.assertEqual(result.html, "hello")

    def test_session_for(self) -> None:
        with patch("apps.scraping.fetching.FetcherSession") as mock_session:
            mock_session.return_value = MagicMock()
            session_for("co.example")
            mock_session.assert_called_once()


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100, FETCH_ALLOW_DYNAMIC=True)
class FetchModeTests(SimpleTestCase):
    """Tests for fetch() with different modes."""

    @patch(
        "apps.scraping.fetching._stealth_get", return_value=_rich_response("https://co.example/x")
    )
    @override_settings(FETCH_ALLOW_STEALTHY=True)
    def test_fetch_stealthy_mode(self, mock_stealth: Mock) -> None:
        result = fetch("https://co.example/x", mode=FetchMode.STEALTHY)
        self.assertEqual(result.fetcher_used, FetchMode.STEALTHY)
        mock_stealth.assert_called_once()

    @override_settings(FETCH_ALLOW_STEALTHY=False)
    def test_fetch_stealthy_disabled_raises(self) -> None:
        with self.assertRaises(FetchError):
            fetch("https://co.example/x", mode=FetchMode.STEALTHY)

    @patch(
        "apps.scraping.fetching._dynamic_get", return_value=_rich_response("https://co.example/x")
    )
    def test_fetch_dynamic_mode(self, mock_dyn: Mock) -> None:
        result = fetch("https://co.example/x", mode=FetchMode.DYNAMIC)
        self.assertEqual(result.fetcher_used, FetchMode.DYNAMIC)

    @patch("apps.scraping.fetching._http_get", side_effect=RuntimeError("boom"))
    def test_fetch_exception_wrapped(self, mock_http: Mock) -> None:
        with self.assertRaises(FetchError):
            fetch("https://co.example/x")

    @patch(
        "apps.scraping.fetching._dynamic_get", return_value=_rich_response("https://co.example/x")
    )
    def test_fetch_capture_xhr(self, mock_dyn: Mock) -> None:
        result = fetch(
            "https://co.example/x", mode=FetchMode.DYNAMIC, capture_xhr=True, xhr_pattern="api"
        )
        self.assertEqual(result.fetcher_used, FetchMode.DYNAMIC)


@override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
class HeadOkExtraTests(SimpleTestCase):
    """Extra edge-case tests for head_ok()."""

    @override_settings(FETCH_ROBOTS_OBEY=True)
    @patch.object(robots, "is_allowed", return_value=False)
    def test_robots_disallowed_returns_false(self, mock_robots: Mock) -> None:
        self.assertEqual(head_ok("https://co.example/x"), (False, 0))

    @patch("apps.scraping.fetching._http_get", side_effect=FetchError("err", url=""))
    def test_fetch_error_returns_false(self, mock_http: Mock) -> None:
        self.assertEqual(head_ok("https://co.example/x"), (False, 0))

    @patch(
        "apps.scraping.fetching._http_get",
        return_value=FakeResponse("https://linkedin.com/x", status=200),
    )
    def test_redirect_to_blocked_raises(self, mock_http: Mock) -> None:
        with self.assertRaises(FetchDomainBlocked):
            head_ok("https://co.example/x")


class FetchRobotsRawTests(SimpleTestCase):
    """Tests for fetch_robots_raw()."""

    @override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
    @patch("apps.scraping.fetching._http_get")
    def test_robots_ok(self, mock_http: Mock) -> None:
        resp = FakeResponse("https://co.example/robots.txt", body="User-agent: *", status=200)
        mock_http.return_value = resp
        status, body = fetch_robots_raw("https://co.example/robots.txt")
        self.assertEqual(status, 200)
        self.assertEqual(body, "User-agent: *")

    @override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
    @patch(
        "apps.scraping.fetching._http_get",
        return_value=FakeResponse("https://co.example/robots.txt", status=404),
    )
    def test_robots_404(self, mock_http: Mock) -> None:
        status, body = fetch_robots_raw("https://co.example/robots.txt")
        self.assertEqual(status, 404)
        self.assertEqual(body, "")

    @override_settings(FETCH_ROBOTS_OBEY=False, FETCH_PER_DOMAIN_RATE=100)
    @patch("apps.scraping.fetching._http_get", side_effect=RuntimeError("boom"))
    def test_robots_exception_returns_zero(self, mock_http: Mock) -> None:
        status, body = fetch_robots_raw("https://co.example/robots.txt")
        self.assertEqual(status, 0)
        self.assertEqual(body, "")

    def test_robots_blocked_domain(self) -> None:
        status, body = fetch_robots_raw("https://linkedin.com/robots.txt")
        self.assertEqual(status, 0)
        self.assertEqual(body, "")
