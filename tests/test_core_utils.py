"""core.utils: normalize_url (STEP-5-ready), client_ip, sha256_of."""

import pytest

from core.utils import client_ip, normalize_url, sha256_of


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Example.com/Job", "https://example.com/Job"),
        ("HTTP://SUB.Example.COM:80/path/", "http://sub.example.com/path"),
        ("https://example.com:443/jobs/", "https://example.com/jobs"),
        ("https://example.com:8443/jobs", "https://example.com:8443/jobs"),
        (
            "https://example.com/jobs/?utm_source=fb&a=1&utm_medium=paid",
            "https://example.com/jobs?a=1",
        ),
        (
            "https://example.com/jobs?a=2&a=1&b=3",
            "https://example.com/jobs?a=1&a=2&b=3",
        ),
        ("https://example.com/jobs/#applied", "https://example.com/jobs"),
        ("https://example.com/jobs?gclid=xyz&fbclid=abc", "https://example.com/jobs"),
        ("  https://Example.com//jobs//vacancy/  ", "https://example.com/jobs/vacancy"),
        ("https://example.com/?utm_term=x", "https://example.com"),
        ("ftp://FTPSERVER.com/file/", "ftp://ftpserver.com/file"),
        (
            "https://example.com/jobs?utm_campaign=1&utm_source=2&utm_medium=3&utm_term=4&utm_content=5",
            "https://example.com/jobs",
        ),
        ("http://example.com:80/", "http://example.com"),
        ("https://example.com/a/b/c/../d", "https://example.com/a/b/c/../d"),
        # Path is case-sensitive: scheme+host lowercase only.
        ("https://Example.com/Job", "https://example.com/Job"),
    ],
)
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_normalize_url_empty_and_none():
    assert normalize_url("") == ""
    assert normalize_url(None) is None
    assert normalize_url("   ") == ""


def test_normalize_url_strips_dot_hosts():
    assert normalize_url("https://example.com./jobs/") == "https://example.com/jobs"


def test_client_ip_forwarded_first_hop():
    class FakeRequest:
        META = {"HTTP_X_FORWARDED_FOR": "203.0.113.7, 10.0.0.1", "REMOTE_ADDR": "127.0.0.1"}

    assert client_ip(FakeRequest()) == "203.0.113.7"


def test_client_ip_fallback_remote_addr():
    class FakeRequest:
        META = {"REMOTE_ADDR": "10.1.2.3"}

    assert client_ip(FakeRequest()) == "10.1.2.3"


def test_sha256_of_stable_and_distinct():
    digest = sha256_of("some job content")
    assert digest == sha256_of("some job content")
    assert len(digest) == 64
    assert digest != sha256_of("some job content!")
