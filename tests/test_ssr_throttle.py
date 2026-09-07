import logging

import pytest
from django.core.cache import cache
from django.test import Client, override_settings
from rest_framework.test import APIClient

PUBLIC_URL = "/api/v1/exams/"
AUTH_URL = "/api/v1/auth/me/"


@pytest.fixture(autouse=True)
def _clear():
    cache.clear()
    yield
    cache.clear()


class TestServiceTokenThrottle:
    @override_settings(SSR_SERVICE_TOKEN="test-token-abc")
    def test_valid_token_bypasses_anon_throttle(self):
        client = APIClient()
        for _ in range(65):
            resp = client.get(PUBLIC_URL, HTTP_X_SERVICE_TOKEN="test-token-abc")
            assert resp.status_code == 200

    @override_settings(SSR_SERVICE_TOKEN="test-token-abc")
    def test_wrong_token_is_throttled_and_logs_warning(self, caplog):
        client = APIClient()
        with caplog.at_level(logging.WARNING, logger="study_tracker.throttling"):
            for _ in range(61):
                resp = client.get(PUBLIC_URL, HTTP_X_SERVICE_TOKEN="wrong-token")
        assert resp.status_code == 429
        assert any("Invalid X-Service-Token" in r.message for r in caplog.records)

    @override_settings(SSR_SERVICE_TOKEN="test-token-abc")
    def test_absent_header_is_throttled(self):
        client = APIClient()
        for _ in range(61):
            resp = client.get(PUBLIC_URL)
        assert resp.status_code == 429

    @override_settings(SSR_SERVICE_TOKEN="")
    def test_empty_setting_with_empty_header_is_throttled(self):
        client = APIClient()
        for _ in range(61):
            resp = client.get(PUBLIC_URL, HTTP_X_SERVICE_TOKEN="")
        assert resp.status_code == 429

    @override_settings(SSR_SERVICE_TOKEN="")
    def test_empty_setting_with_nonempty_header_is_throttled(self):
        client = APIClient()
        for _ in range(61):
            resp = client.get(PUBLIC_URL, HTTP_X_SERVICE_TOKEN="any-value")
        assert resp.status_code == 429

    @override_settings(SSR_SERVICE_TOKEN="test-token-abc")
    def test_valid_token_on_authenticated_endpoint_still_401(self):
        client = APIClient()
        resp = client.get(AUTH_URL, HTTP_X_SERVICE_TOKEN="test-token-abc")
        assert resp.status_code in (401, 403)

    @override_settings(SSR_SERVICE_TOKEN="test-token-abc")
    def test_one_char_altered_is_rejected(self):
        client = APIClient()
        for _ in range(61):
            resp = client.get(PUBLIC_URL, HTTP_X_SERVICE_TOKEN="test-token-abd")
        assert resp.status_code == 429


class TestExamsAdminChangelist:
    @pytest.fixture(autouse=True)
    def _setup_admin(self, db):
        from tests.factories import AdminUserFactory

        self.admin = AdminUserFactory()
        self.client = Client()
        self.client.force_login(self.admin)

    def test_conducting_body_changelist(self):
        resp = self.client.get("/admin/exams/conductingbody/")
        assert resp.status_code == 200

    def test_exam_changelist(self):
        resp = self.client.get("/admin/exams/exam/")
        assert resp.status_code == 200

    def test_exam_cycle_changelist(self):
        resp = self.client.get("/admin/exams/examcycle/")
        assert resp.status_code == 200

    def test_exam_stage_changelist(self):
        resp = self.client.get("/admin/exams/examstage/")
        assert resp.status_code == 200

    def test_exam_eligibility_changelist(self):
        resp = self.client.get("/admin/exams/exameligibility/")
        assert resp.status_code == 200

    def test_exam_date_change_changelist(self):
        resp = self.client.get("/admin/exams/examdatechange/")
        assert resp.status_code == 200

    def test_saved_exam_changelist(self):
        resp = self.client.get("/admin/exams/savedexam/")
        assert resp.status_code == 200

    def test_exam_changelist_query_budget(self, django_assert_max_num_queries):
        from apps.exams.models import ConductingBody, Exam

        body = ConductingBody.objects.create(
            name="Test Body", slug="test-body", body_type="central"
        )
        for i in range(50):
            Exam.objects.create(
                name=f"Exam {i}",
                slug=f"exam-{i}",
                conducting_body=body,
                category="ssc",
                level="national",
            )
        with django_assert_max_num_queries(14):
            resp = self.client.get("/admin/exams/exam/")
        assert resp.status_code == 200
