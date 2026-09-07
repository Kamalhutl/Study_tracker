from datetime import timedelta

import pytest
from django.utils import timezone

from apps.exams.filters import ExamFilter
from apps.exams.models import ConductingBody, CycleStatus, Exam, ExamCycle, ExamEligibility

pytestmark = pytest.mark.django_db


class TestExamFilter:
    def test_filter_q_empty(self):
        body = ConductingBody.objects.create(name="A", slug="a", body_type="central")
        Exam.objects.create(
            name="Test", slug="test", conducting_body=body, category="other", level="national"
        )
        queryset = Exam.objects.all()
        filter_obj = ExamFilter(data={"q": ""}, queryset=queryset)
        self.assertQuerysetEqual(filter_obj.qs, queryset)

    def test_filter_q_icontains(self):
        body = ConductingBody.objects.create(name="XYZ", slug="xyz", body_type="central")
        exam1 = Exam.objects.create(
            name="Alpha",
            short_name="A",
            slug="a",
            conducting_body=body,
            category="other",
            level="national",
        )
        Exam.objects.create(
            name="Beta",
            short_name="B",
            slug="b",
            conducting_body=body,
            category="other",
            level="national",
        )
        Exam.objects.create(
            name="Gamma",
            short_name="G",
            slug="g",
            conducting_body=body,
            category="other",
            level="national",
        )
        # decoy that should not match
        body2 = ConductingBody.objects.create(name="ZYX", slug="zyx", body_type="central")
        Exam.objects.create(
            name="Decoy",
            short_name="D",
            slug="d",
            conducting_body=body2,
            category="other",
            level="national",
        )
        filter_obj = ExamFilter(data={"q": "Al"}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam1}

    def test_filter_body(self):
        body1 = ConductingBody.objects.create(name="One", slug="one", body_type="central")
        body2 = ConductingBody.objects.create(name="Two", slug="two", body_type="central")
        exam1 = Exam.objects.create(
            name="E1", slug="e1", conducting_body=body1, category="other", level="national"
        )
        exam2 = Exam.objects.create(
            name="E2", slug="e2", conducting_body=body2, category="other", level="national"
        )
        exam3 = Exam.objects.create(
            name="E3", slug="e3", conducting_body=body1, category="other", level="national"
        )
        # decoy
        body3 = ConductingBody.objects.create(name="Three", slug="three", body_type="central")
        Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body3, category="other", level="national"
        )
        filter_obj = ExamFilter(data={"body": "one,two"}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam1, exam2, exam3}
        # with whitespace
        filter_obj = ExamFilter(data={"body": " one , two "}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam1, exam2, exam3}

    def test_filter_category(self):
        cat1 = "civil_services"
        cat2 = "banking"
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        exam1 = Exam.objects.create(
            name="E1", slug="e1", conducting_body=body, category=cat1, level="national"
        )
        exam2 = Exam.objects.create(
            name="E2", slug="e2", conducting_body=body, category=cat2, level="national"
        )
        exam3 = Exam.objects.create(
            name="E3", slug="e3", conducting_body=body, category=cat1, level="national"
        )
        _ = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="national"
        )
        filter_obj = ExamFilter(
            data={"category": "civil_services,banking"}, queryset=Exam.objects.all()
        )
        assert set(filter_obj.qs) == {exam1, exam2, exam3}
        # whitespace
        filter_obj = ExamFilter(
            data={"category": " civil_services , banking "}, queryset=Exam.objects.all()
        )
        assert set(filter_obj.qs) == {exam1, exam2, exam3}

    def test_filter_level(self):
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        exam1 = Exam.objects.create(
            name="E1", slug="e1", conducting_body=body, category="other", level="national"
        )
        exam2 = Exam.objects.create(
            name="E2", slug="e2", conducting_body=body, category="other", level="state"
        )
        exam3 = Exam.objects.create(
            name="E3", slug="e3", conducting_body=body, category="other", level="national"
        )
        exam_decoy = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="state"
        )  # but we filter national only
        filter_obj = ExamFilter(data={"level": "national,state"}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam1, exam2, exam3, exam_decoy}  # both
        filter_obj = ExamFilter(data={"level": "national"}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam1, exam3}

    def test_filter_status(self):
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        exam = Exam.objects.create(
            name="E", slug="e", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam,
            year=2025,
            cycle_label="2025",
            status=CycleStatus.ANNOUNCED,
            is_published=True,
            verified_by_human=True,
        )
        ExamCycle.objects.create(
            exam=exam,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.NOTIFICATION_OUT,
            is_published=True,
            verified_by_human=True,
        )
        # decoy: exam with older cycle status as searched, latest different
        exam_decoy = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam_decoy,
            year=2024,
            cycle_label="2024",
            status=CycleStatus.ANNOUNCED,
            is_published=True,
            verified_by_human=True,
        )
        ExamCycle.objects.create(
            exam=exam_decoy,
            year=2025,
            cycle_label="2025",
            status=CycleStatus.NOTIFICATION_OUT,
            is_published=True,
            verified_by_human=True,
        )
        filter_obj = ExamFilter(data={"status": CycleStatus.ANNOUNCED}, queryset=Exam.objects.all())
        # only the first exam should match (its latest is ANNOUNCED? No, latest is NOTIFICATION_OUT, so not match)
        # Actually we need latest status to be searched. For exam, latest is NOTIFICATION_OUT, so not match.
        # For decoy, latest is NOTIFICATION_OUT, so also not match. So empty.
        # Let's adjust: we want exam to have latest ANNOUNCED, so set cycle2 to something else.
        # Reset: make cycle2 status also ANNOUNCED? No, we want to test that we pick the latest.
        # Let's create a new exam where the latest is ANNOUNCED.
        exam2 = Exam.objects.create(
            name="E2", slug="e2", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam2,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            is_published=True,
            verified_by_human=True,
        )
        # decoy with older ANNOUNCED but latest NOTIFICATION_OUT
        exam_decoy2 = Exam.objects.create(
            name="Decoy2", slug="dec2", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam_decoy2,
            year=2025,
            cycle_label="2025",
            status=CycleStatus.ANNOUNCED,
            is_published=True,
            verified_by_human=True,
        )
        ExamCycle.objects.create(
            exam=exam_decoy2,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.NOTIFICATION_OUT,
            is_published=True,
            verified_by_human=True,
        )
        filter_obj = ExamFilter(data={"status": CycleStatus.ANNOUNCED}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam2}

    def test_filter_applications_open(self):
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        exam = Exam.objects.create(
            name="E", slug="e", conducting_body=body, category="other", level="national"
        )
        now = timezone.now().date()
        # open cycle
        ExamCycle.objects.create(
            exam=exam,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            application_start=now - timedelta(days=1),
            application_end=now + timedelta(days=1),
            is_published=True,
            verified_by_human=True,
        )
        # decoy: closed cycle
        exam_decoy = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam_decoy,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            application_start=now - timedelta(days=2),
            application_end=now - timedelta(days=1),
            is_published=True,
            verified_by_human=True,
        )
        filter_obj = ExamFilter(data={"applications_open": True}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam}
        filter_obj = ExamFilter(data={"applications_open": False}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == set(Exam.objects.all())  # returns all when false

    def test_filter_upcoming(self):
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        now = timezone.now().date()
        exam = Exam.objects.create(
            name="E", slug="e", conducting_body=body, category="other", level="national"
        )
        # create a cycle with notification_date in next 5 days
        ExamCycle.objects.create(
            exam=exam,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            notification_date=now + timedelta(days=3),
            is_published=True,
            verified_by_human=True,
        )
        # decoy: notification_date after 10 days, outside 5-day window
        exam_decoy = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="national"
        )
        ExamCycle.objects.create(
            exam=exam_decoy,
            year=2026,
            cycle_label="2026",
            status=CycleStatus.ANNOUNCED,
            notification_date=now + timedelta(days=10),
            is_published=True,
            verified_by_human=True,
        )
        filter_obj = ExamFilter(data={"upcoming_within_days": 5}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam}
        # non-integer value (Decimal regression): should not crash
        filter_obj = ExamFilter(data={"upcoming_within_days": "5.0"}, queryset=Exam.objects.all())
        # should still work, cast to int
        assert set(filter_obj.qs) == {exam}

    def test_filter_allow_final_year(self):
        body = ConductingBody.objects.create(name="B", slug="b", body_type="central")
        exam = Exam.objects.create(
            name="E", slug="e", conducting_body=body, category="other", level="national"
        )
        ExamEligibility.objects.create(exam=exam, allow_final_year_appearing=True)
        exam_decoy = Exam.objects.create(
            name="Decoy", slug="dec", conducting_body=body, category="other", level="national"
        )
        ExamEligibility.objects.create(exam=exam_decoy, allow_final_year_appearing=False)
        filter_obj = ExamFilter(data={"allow_final_year": True}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == {exam}
        filter_obj = ExamFilter(data={"allow_final_year": False}, queryset=Exam.objects.all())
        assert set(filter_obj.qs) == set(Exam.objects.all())  # returns all when false

    def assertQuerysetEqual(self, qs, expected):
        assert set(qs) == set(expected)
