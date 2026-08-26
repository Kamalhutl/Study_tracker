"""Robots parser tests — no network, no real Scrapling."""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.scraping import robots

SAMPLE = """\
User-agent: *
Disallow: /private/
Allow: /public/
Crawl-delay: 0.5
Sitemap: https://example.com/sitemap.xml

User-agent: StudyTrackerBot
Disallow:
Allow: /careers
Crawl-delay: 2

User-agent: OtherBot
Disallow: /
Session-Probe: /ping
"""


class FetchNowTests(SimpleTestCase):
    def test_parses_blocks_and_sitemaps(self) -> None:
        rules = robots.fetch_now("https://example.com/", body=SAMPLE)
        self.assertEqual(len(rules.blocks), 3)
        self.assertEqual(rules.sitemaps, ["https://example.com/sitemap.xml"])

    def test_select_for_picks_longest_matching_ua(self) -> None:
        rules = robots.fetch_now("https://example.com/", body=SAMPLE)
        block = rules.select_for(robots.USER_AGENT_KEY)
        self.assertEqual(block.crawl_delay, 2)
        self.assertTrue(block.allowed("/careers")[0])
        # The StudyTrackerBot block only *disallows nothing* (blank Disallow: line
        # means "no restriction" per the robots spec) — /private/ is open to it.
        self.assertTrue(block.allowed("/private/")[0])

    def test_wildcard_block_applies_when_no_specific_ua(self) -> None:
        rules = robots.fetch_now("https://example.com/", body=SAMPLE)
        block = rules.select_for("random-crawler/1.0")
        self.assertEqual(block.crawl_delay, 0.5)
        self.assertFalse(block.allowed("/private/")[0])
        self.assertTrue(block.allowed("/public/")[0])

    def test_specific_allow_wins_over_unspecific_disallow(self) -> None:
        body = "User-agent: *\nDisallow: /\nAllow: /careers/\n"
        rules = robots.fetch_now("https://x.example/", body=body)
        block = rules.select_for("*")
        self.assertFalse(block.allowed("/secret")[0])
        self.assertTrue(block.allowed("/careers/")[0])

    def test_session_probes_are_captured(self) -> None:
        rules = robots.fetch_now("https://example.com/", body=SAMPLE)
        other = rules.select_for("OtherBot")
        self.assertEqual(other.session_probes, ["/ping"])

    def test_empty_body_allows_everything(self) -> None:
        rules = robots.fetch_now("https://example.com/", body="")
        self.assertTrue(rules.select_for("*").allowed("/anything")[0])


class IsAllowedTests(SimpleTestCase):
    def setUp(self) -> None:
        for host in ("missing.example", "corp.example", "dead.example"):
            robots.invalidate(f"https://{host}/")  # wipe cross-test cache

    def test_missing_robots_allows(self) -> None:
        with patch.object(robots, "fetch_robots_raw", return_value=(404, "")):
            self.assertTrue(robots.is_allowed("https://missing.example/secret"))

    def test_disallow_path_blocked(self) -> None:
        body = "User-agent: StudyTrackerBot\nDisallow: /internal\n"
        with patch.object(robots, "fetch_robots_raw", return_value=(200, body)):
            self.assertFalse(robots.is_allowed("https://corp.example/internal/x"))
            self.assertTrue(robots.is_allowed("https://corp.example/careers"))

    def test_failed_fetch_allows_by_default(self) -> None:
        with patch.object(robots, "fetch_robots_raw", return_value=(500, "")):
            self.assertTrue(robots.is_allowed("https://dead.example/"))

    def test_blank_disallow_path_allows(self) -> None:
        body = "User-agent: StudyTrackerBot\nDisallow:\n"
        with patch.object(robots, "fetch_robots_raw", return_value=(200, body)):
            self.assertTrue(robots.is_allowed("https://corp.example/anything"))
