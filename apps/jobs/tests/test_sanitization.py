from apps.jobs.services import _sanitize_html


def test_sanitize_removes_script():
    html = "<script>alert(1)</script><p>Hello</p>"
    sanitized = _sanitize_html(html)
    assert "<script>" not in sanitized
    assert "alert(1)" not in sanitized
    assert "<p>Hello</p>" in sanitized


def test_sanitize_removes_javascript_link():
    html = '<a href="javascript:alert(1)">Click</a>'
    sanitized = _sanitize_html(html)
    assert "javascript:" not in sanitized
    assert "Click" in sanitized
    # href should be stripped or removed
    assert "href" not in sanitized or sanitized.find("href") == -1


def test_sanitize_allows_safe_tags():
    html = "<p><strong>bold</strong> <em>italic</em> <u>underline</u> <ul><li>item</li></ul></p>"
    sanitized = _sanitize_html(html)
    assert "<p>" in sanitized
    assert "<strong>" in sanitized
    assert "<em>" in sanitized
    assert "<u>" in sanitized
    assert "<ul>" in sanitized
    assert "<li>" in sanitized


def test_sanitize_strips_style():
    html = "<style>body {color: red;}</style>"
    sanitized = _sanitize_html(html)
    assert "<style>" not in sanitized


def test_sanitize_strips_iframe():
    html = '<iframe src="http://example.com"></iframe>'
    sanitized = _sanitize_html(html)
    assert "<iframe>" not in sanitized


def test_sanitize_allows_a_with_safe_attrs():
    html = '<a href="http://example.com" title="Example" onclick="alert(1)">Link</a>'
    sanitized = _sanitize_html(html)
    assert 'href="http://example.com"' in sanitized
    assert 'title="Example"' in sanitized
    assert "onclick" not in sanitized


def test_sanitize_strips_data_urls():
    html = '<img src="data:image/png;base64,abc">'
    sanitized = _sanitize_html(html)
    # img is not allowed, so it should be stripped
    assert "img" not in sanitized


def test_sanitize_empty():
    assert _sanitize_html("") == ""
    assert _sanitize_html(None) == ""


def test_sanitize_strips_comments():
    html = "<!-- comment --><p>text</p>"
    sanitized = _sanitize_html(html)
    assert "comment" not in sanitized
    assert "<p>text</p>" in sanitized
