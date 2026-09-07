import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.exams.models import ConductingBody, CycleStatus, Exam, ExamCycle
from tests.factories import UserFactory

pytestmark = pytest.mark.django_db


class TestExamList:
    def test_list_public_exams(self, client):
        body = ConductingBody.objects.create(name="UPSC", slug="upsc", body_type="central")
        Exam.objects.create(
            name="Civil Services",
            slug="cse",
            conducting_body=body,
            category="civil_services",
            level="national",
            is_active=True,
        )
        url = reverse("exam-list")
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["slug"] == "cse"

    def test_search_trigram(self, client):
        body = ConductingBody.objects.create(name="UPSC", slug="upsc2", body_type="central")
        _ = Exam.objects.create(
            name="Civil Services",
            slug="cse2",
            conducting_body=body,
            category="civil_services",
            level="national",
            is_active=True,
        )
        url = reverse("exam-list") + "?q=Civil"
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 1
        # Decoy
        body2 = ConductingBody.objects.create(name="XYZ Corp", slug="xyz2", body_type="central")
        Exam.objects.create(
            name="Qwerty",
            slug="qwerty2",
            conducting_body=body2,
            category="other",
            level="national",
            is_active=True,
        )
        response = client.get(url)
        assert len(response.data["results"]) == 1  # only civil matches


class TestSaveExam:
    def test_save_requires_auth(self, client):
        body = ConductingBody.objects.create(name="UPSC", slug="upsc3", body_type="central")
        _ = Exam.objects.create(
            name="NDA",
            slug="nda",
            conducting_body=body,
            category="defence",
            level="national",
            is_active=True,
        )
        url = reverse("save-exam", kwargs={"slug": "nda"})
        api_client = APIClient()  # unauthenticated
        response = api_client.post(url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_save_idempotent(self, client):
        user = UserFactory()
        api_client = APIClient()
        api_client.force_authenticate(user=user)
        body = ConductingBody.objects.create(name="UPSC", slug="upsc4", body_type="central")
        _ = Exam.objects.create(
            name="CDS",
            slug="cds",
            conducting_body=body,
            category="defence",
            level="national",
            is_active=True,
        )
        url = reverse("save-exam", kwargs={"slug": "cds"})
        response = api_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["created"] is True
        response = api_client.post(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["created"] is False
        # unsave
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["deleted"] is True


class TestCalendar:
    def test_calendar_flat_events(self, client):
        from datetime import date

        body = ConductingBody.objects.create(name="UPSC", slug="upsc5", body_type="central")
        exam = Exam.objects.create(
            name="CSE",
            slug="cse5",
            conducting_body=body,
            category="civil_services",
            level="national",
            is_active=True,
        )
        cycle = ExamCycle.objects.create(
            exam=exam,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            notification_date=date(2026, 2, 15),
            application_start=date(2026, 2, 15),
            application_end=date(2026, 3, 15),
            is_published=True,
            verified_by_human=True,
        )
        url = reverse("calendar") + "?from=2026-02-01&to=2026-03-31"
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK
        data = response.data
        assert len(data) >= 3  # notification, start, end
        event_types = [e["event_type"] for e in data]
        assert "notification" in event_types
        assert "application_start" in event_types
        assert "application_end" in event_types
        # Tentative propagation
        cycle.stages.create(
            stage_order=1,
            name="Prelims",
            mode="online_cbt",
            date_start=date(2026, 6, 15),
            is_date_tentative=True,
        )
        url = reverse("calendar") + "?from=2026-06-01&to=2026-06-30"
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK
        stage_events = [e for e in response.data if e["event_type"] == "stage_exam"]
        assert len(stage_events) == 1
        assert stage_events[0]["is_tentative"] is True

    def test_calendar_closure_bug(self, client):
        from datetime import date

        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        # Create three exams with distinct official_urls and cycles with dates in window
        exam1 = Exam.objects.create(
            name="E1",
            slug="e1",
            conducting_body=body,
            category="other",
            level="national",
            official_url="https://e1.example",
        )
        exam2 = Exam.objects.create(
            name="E2",
            slug="e2",
            conducting_body=body,
            category="other",
            level="national",
            official_url="https://e2.example",
        )
        exam3 = Exam.objects.create(
            name="E3",
            slug="e3",
            conducting_body=body,
            category="other",
            level="national",
            official_url="https://e3.example",
        )
        # Create cycles with notification_date inside 2026-02-01 to 2026-03-31
        _ = ExamCycle.objects.create(
            exam=exam1,
            year=2026,
            cycle_label="c1",
            status=CycleStatus.ANNOUNCED,
            notification_date=date(2026, 2, 10),
            is_published=True,
            verified_by_human=True,
        )
        _ = ExamCycle.objects.create(
            exam=exam2,
            year=2026,
            cycle_label="c2",
            status=CycleStatus.ANNOUNCED,
            notification_date=date(2026, 2, 20),
            is_published=True,
            verified_by_human=True,
        )
        _ = ExamCycle.objects.create(
            exam=exam3,
            year=2026,
            cycle_label="c3",
            status=CycleStatus.ANNOUNCED,
            notification_date=date(2026, 3, 1),
            is_published=True,
            verified_by_human=True,
        )
        url = reverse("calendar") + "?from=2026-02-01&to=2026-03-31"
        response = client.get(url)
        assert response.status_code == status.HTTP_200_OK
        events = response.data
        # Each event should have official_url matching its exam's official_url
        for event in events:
            exam_slug = event["exam_slug"]
            if exam_slug == "e1":
                assert event["official_url"] == "https://e1.example"
            elif exam_slug == "e2":
                assert event["official_url"] == "https://e2.example"
            elif exam_slug == "e3":
                assert event["official_url"] == "https://e3.example"
            else:
                raise AssertionError(f"Unexpected exam_slug {exam_slug}")
        # Also assert no event has wrong official_url
        for event in events:
            exam_slug = event["exam_slug"]
            if exam_slug == "e1":
                assert event["official_url"] != "https://e2.example"
                assert event["official_url"] != "https://e3.example"
            # etc.
