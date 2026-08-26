"""Extraction helpers — keyword rules, JSON-LD, anchor harvesting, sitemaps."""

from __future__ import annotations

from apps.career_detection import extract


class TestHostHelpers:
    def test_host_of(self):
        assert extract.host_of("https://Careers.Example.COM/x?y=1") == "careers.example.com"
        assert extract.host_of("ftp://example.com") == "example.com"

    def test_path_of(self):
        assert extract.path_of("https://example.com/company/careers/?a=1") == "/company/careers/"
        assert extract.path_of("https://example.com") == "/"

    def test_is_ats_host(self):
        assert extract.is_ats_host("boards.greenhouse.io")
        assert extract.is_ats_host("jobs.lever.co")
        assert extract.is_ats_host("x.ashbyhq.com")
        assert not extract.is_ats_host("example.com")
        assert not extract.is_ats_host("myworkdayjobs.com")

    def test_is_workday_host(self):
        assert extract.is_workday_host("acme.myworkdayjobs.com")
        assert not extract.is_workday_host("boards.greenhouse.io")

    def test_is_career_subdomain_host(self):
        assert extract.is_career_subdomain_host("careers.example.com")
        assert extract.is_career_subdomain_host("jobs.example.com")
        assert not extract.is_career_subdomain_host("blog.example.com")

    def test_registrable_domain(self):
        assert extract.registrable_domain("careers.acme.com") == "acme.com"
        assert extract.registrable_domain("www.acme.com") == "acme.com"
        assert extract.registrable_domain("jobs.acme.co.uk") == "acme.co.uk"
        assert extract.registrable_domain("acme.com") == "acme.com"


class TestKeywordMatching:
    def test_path_components_split_on_hyphens(self):
        assert extract.path_has_career_keyword("/company/careers")
        assert extract.path_has_career_keyword("/careers-2025")
        assert extract.path_has_career_keyword("/openings_now")  # underscore split

    def test_partial_component_does_not_match(self):
        assert not extract.path_has_career_keyword("/carerra-tires")
        assert not extract.path_has_career_keyword("/recareers-x")

    def test_component_prefix_starts_ok(self):
        assert extract.path_has_career_keyword("/careers-website")

    def test_noise_tokens(self):
        assert extract.path_has_noise_token("/blog/careers")
        assert extract.path_has_noise_token("/careers-news")

    def test_text_matching_is_bounded(self):
        assert extract.text_has_career_keyword("We Are Hiring!")
        assert extract.text_has_career_keyword("open careers page")
        assert not extract.text_has_career_keyword("careerscorner")
        assert not extract.text_has_career_keyword("notcareerish")

    def test_text_multiword_phrase_matches_hyphen_keyword(self):
        """§6.3: 'Join Us' matches 'join-us' via hyphen normalization; carerra never."""
        assert extract.text_has_career_keyword("Join Us")
        assert extract.text_has_career_keyword("Work With Us")
        assert not extract.text_has_career_keyword("carerra tires")

    def test_text_matching_case_insensitive(self):
        assert extract.text_has_career_keyword("CAREERS AT ACME")


class TestJsonLd:
    HTML = """
    <html><head>
      <script type="application/ld+json">
      {"@context": "https://schema.org", "@type": "JobPosting", "title": "One"}
      </script>
      <script type="application/ld+json">
      [{"@type": "JobPosting", "title": "Two"}, {"@type": "Organization", "name": "Acme"}]
      </script>
      <script type="application/ld+json">
      {"@context": "https://schema.org", "@type": "ItemList",
       "itemListElement": [{"@type": "JobPosting", "title": "Three"}]}
      </script>
      <script type="application/ld+json">not json {</script>
    </head></html>
    """

    def test_parsed_json_ld_collects_dicts_and_lists(self):
        nodes = extract.parsed_json_ld(self.HTML)
        assert len(nodes) == 4  # 3 scripts with data; malformed one skipped

    def test_job_postings_from_json_ld(self):
        postings = extract.job_postings_from_json_ld(self.HTML)
        assert {p["title"] for p in postings} == {"One", "Two", "Three"}

    def test_has_itemlist_with_jobpostings(self):
        assert extract.has_itemlist_jobpostings(self.HTML)

    def test_page_has_jobposting_true(self):
        assert extract.page_has_jobposting(self.HTML)

    def test_empty_html_false(self):
        assert not extract.page_has_jobposting("")
        assert extract.parsed_json_ld("") == []

    def test_no_itemlist_false(self):
        html = '<script type="application/ld+json">{"@type": "Organization"}</script>'
        assert not extract.has_itemlist_jobpostings(html)
        assert not extract.page_has_jobposting(html)


class TestAnchorHarvesting:
    HTML = (
        "<html><body>"
        '<header><a href="/careers">Careers</a><a href="/about">About</a></header>'
        '<nav><a href="/jobs">Jobs</a></nav>'
        '<main><a href="/blog">Blog</a></main>'
        '<footer><a href="/join-us">Join Us</a></footer>'
        '<a href="mailto:hr@acme.test">HR</a>'
        "</body></html>"
    )

    def test_links_from_html_all_absolutized(self):
        links = extract.links_from_html(self.HTML, "https://acme.test/")
        urls = {u for u, _ in links}
        assert urls == {
            "https://acme.test/careers",
            "https://acme.test/about",
            "https://acme.test/jobs",
            "https://acme.test/blog",
            "https://acme.test/join-us",
        }

    def test_region_links_header_includes_nav(self):
        links = dict(extract.region_links_from_html(self.HTML, "https://acme.test/", "header"))
        assert set(links) == {
            "https://acme.test/careers",
            "https://acme.test/about",
            "https://acme.test/jobs",
        }

    def test_region_links_footer_only_footer(self):
        links = dict(extract.region_links_from_html(self.HTML, "https://acme.test/", "footer"))
        assert set(links) == {"https://acme.test/join-us"}

    def test_mailto_skipped(self):
        links = extract.links_from_html(self.HTML, "https://acme.test/")
        assert not any(u.startswith("mailto:") for u, _ in links)


class TestTitleAndText:
    def test_title_from_html(self):
        html = "<html><head><title>   Careers @ Acme   </title></head></html>"
        assert extract.title_from_html(html) == "Careers @ Acme"

    def test_title_from_og_fallback(self):
        html = '<html><head><meta property="og:title" content="Join the future"></head></html>'
        assert extract.title_from_html(html) == "Join the future"

    def test_title_empty(self):
        assert extract.title_from_html("<html></html>") == ""

    def test_visible_text(self):
        html = "<html><body><p>Hello <b>world</b></p><script>var x=1;</script></body></html>"
        assert "Hello world" in extract.visible_text(html)

    def test_has_no_openings_text(self):
        assert extract.has_no_openings_text("<p>We have no open positions right now.</p>")
        assert extract.has_no_openings_text("<p>Thanks but there are no vacancies.</p>")
        assert not extract.has_no_openings_text("<p>We are hiring engineers.</p>")


class TestJobLinkHeuristics:
    def test_looks_like_job_posting_patterns(self):
        assert extract.looks_like_job_posting("https://boards.greenhouse.io/acme/edge/jobs/42")
        assert extract.looks_like_job_posting("https://jobs.lever.co/acme/o/engineer")
        assert extract.looks_like_job_posting("https://jobs.ashbyhq.com/acme/ffcc99")
        assert extract.looks_like_job_posting("https://acme.smartrecruiters.com/position/42")
        assert extract.looks_like_job_posting("https://acme.myworkdayjobs.com/jobs/42")
        assert extract.looks_like_job_posting("https://example.com/job/engineer")

    def test_looks_like_job_posting_trailing_digit(self):
        assert extract.looks_like_job_posting("https://example.com/careers/3033")

    def test_not_job_posting(self):
        assert not extract.looks_like_job_posting("https://example.com/careers")
        assert not extract.looks_like_job_posting("https://example.com/about")

    def test_sample_titles_limit_and_dedupe(self):
        html = (
            "<html><body>"
            '<a href="/job/1">Engineer A</a>'
            '<a href="/job/2">Engineer A</a>'
            '<a href="/job/3">Designer</a>'
            '<a href="/job/4">Product Lead</a>'
            '<a href="/job/5">QA Tester</a>'
            '<a href="/job/6">Ops</a>'
            "</body></html>"
        )
        links = extract.links_from_html(html, "https://example.com/")
        titles = extract.sample_titles_from_html(html, links, limit=3)
        assert titles == ["Engineer A", "Designer", "Product Lead"]

    def test_count_job_links(self):
        links = [
            ("https://example.com/job/1", "A"),
            ("https://example.com/job/2", "B"),
            ("https://example.com/job/3", "C"),
            ("https://example.com/about", "About"),
        ]
        assert extract.count_job_links(links) == 3

    def test_trailing_component(self):
        assert extract.trailing_component("https://example.com/jobs/30401") == "30401"
        assert extract.trailing_component("https://example.com/jobs/") == "jobs"


class TestSitemap:
    def test_parse_urlset(self):
        body = (
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<url><loc>https://acme.test/careers</loc></url>"
            "<url><loc>https://acme.test/about</loc></url>"
            "</urlset>"
        )
        is_index, urls = extract.parse_sitemap(body)
        assert not is_index
        assert urls == ["https://acme.test/careers", "https://acme.test/about"]

    def test_parse_index(self):
        body = (
            '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            "<sitemap><loc>https://acme.test/sitemap-1.xml</loc></sitemap>"
            "</sitemapindex>"
        )
        is_index, urls = extract.parse_sitemap(body)
        assert is_index
        assert urls == ["https://acme.test/sitemap-1.xml"]

    def test_parse_garbage(self):
        is_index, urls = extract.parse_sitemap("<<<not sitemap>>>")
        assert not is_index
        assert urls == []
