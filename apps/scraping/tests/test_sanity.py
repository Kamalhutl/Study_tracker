import pytest
from django.test import override_settings

from apps.scraping.sanity import RunVerdict, evaluate_run


class TestEvaluateRun:
    @pytest.mark.parametrize(
        "run_status,jobs_found,last_jobs_seen,expected_verdict,expected_reason_substring",
        [
            # Rule 1: run_status not success
            ("running", 100, 100, RunVerdict.UNTRUSTED, "status is running"),
            ("failed", 0, 50, RunVerdict.UNTRUSTED, "status is failed"),
            ("partial", 10, 10, RunVerdict.UNTRUSTED, "status is partial"),
            # Rule 2: below baseline -> TRUSTED
            ("success", 40, 3, RunVerdict.TRUSTED, "Below baseline"),
            ("success", 0, 0, RunVerdict.TRUSTED, "Below baseline"),
            ("success", 100, 4, RunVerdict.TRUSTED, "Below baseline"),
            # Rule 3: zero found, baseline > 0 -> QUARANTINED
            ("success", 0, 12, RunVerdict.QUARANTINED, "Found 0 jobs"),
            # Rule 4: drop below ratio -> QUARANTINED
            ("success", 40, 100, RunVerdict.QUARANTINED, "Drop ratio"),
            ("success", 19, 40, RunVerdict.QUARANTINED, "Drop ratio"),
            ("success", 3, 10, RunVerdict.QUARANTINED, "Drop ratio"),
            # Rule 5: otherwise TRUSTED
            ("success", 40, 39, RunVerdict.TRUSTED, "Within acceptable range"),
            ("success", 20, 40, RunVerdict.TRUSTED, "Within acceptable range"),
            ("success", 40, 80, RunVerdict.TRUSTED, "Within acceptable range"),
        ],
    )
    def test_evaluate_run_scenarios(
        self, run_status, jobs_found, last_jobs_seen, expected_verdict, expected_reason_substring
    ):
        verdict, reason = evaluate_run(
            run_status=run_status,
            jobs_found=jobs_found,
            last_jobs_seen=last_jobs_seen,
        )
        assert verdict == expected_verdict
        assert expected_reason_substring in reason

    def test_boundary_conditions(self):
        # Exactly at ratio boundary (40 found, last 40 -> 40 >= 20, TRUSTED)
        with override_settings(SCRAPE_SANITY_DROP_RATIO=0.5):
            verdict, reason = evaluate_run(run_status="success", jobs_found=40, last_jobs_seen=80)
            # 40 >= 80*0.5 = 40 => TRUSTED
            assert verdict == RunVerdict.TRUSTED
            assert "Within acceptable range" in reason

            # Just below ratio (39 found, last 80 -> 39 < 40 => QUARANTINED)
            verdict, reason = evaluate_run(run_status="success", jobs_found=39, last_jobs_seen=80)
            assert verdict == RunVerdict.QUARANTINED
            assert "Drop ratio" in reason

            # Check the min baseline threshold: last_jobs_seen == MIN_BASELINE-1 -> TRUSTED even with low found
            with override_settings(SCRAPE_SANITY_MIN_BASELINE=5):
                verdict, reason = evaluate_run(run_status="success", jobs_found=0, last_jobs_seen=4)
                assert verdict == RunVerdict.TRUSTED
                assert "Below baseline" in reason

                # baseline exactly 5 -> quarantine applies if 0 found
                verdict, reason = evaluate_run(run_status="success", jobs_found=0, last_jobs_seen=5)
                assert verdict == RunVerdict.QUARANTINED

    def test_settings_override(self):
        # Use custom settings to test overrides
        with override_settings(
            SCRAPE_SANITY_DROP_RATIO=0.8,
            SCRAPE_SANITY_MIN_BASELINE=10,
        ):
            # last_jobs_seen 8 < baseline 10 => TRUSTED
            verdict, reason = evaluate_run(run_status="success", jobs_found=5, last_jobs_seen=8)
            assert verdict == RunVerdict.TRUSTED

            # now baseline satisfied, drop ratio 0.8: 12 < 20*0.8=16 => QUARANTINED
            verdict, reason = evaluate_run(run_status="success", jobs_found=12, last_jobs_seen=20)
            assert verdict == RunVerdict.QUARANTINED
            assert "Drop ratio" in reason
