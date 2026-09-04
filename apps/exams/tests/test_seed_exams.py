from django.core.management import call_command
from django.test import TestCase

from apps.exams.models import ConductingBody, Exam, ExamCycle, ExamEligibility


class SeedExamsTest(TestCase):
    def test_seed_creates_twelve_exams_idempotent(self):
        call_command("seed_exams")
        # Check counts
        self.assertEqual(ConductingBody.objects.count(), 8)  # 8 distinct bodies
        self.assertEqual(Exam.objects.count(), 12)
        self.assertGreater(ExamCycle.objects.count(), 0)
        self.assertGreater(ExamEligibility.objects.count(), 0)

        # Run again and verify counts unchanged
        call_command("seed_exams")
        self.assertEqual(ConductingBody.objects.count(), 8)
        self.assertEqual(Exam.objects.count(), 12)
        self.assertEqual(ExamCycle.objects.count(), 12)  # One cycle per exam, all unchanged

        # Check all short_names present and unique
        short_names = list(Exam.objects.values_list("short_name", flat=True))
        self.assertNotIn("", short_names)
        self.assertEqual(len(short_names), len(set(short_names)))

    def test_cycles_unpublished_and_unverified(self):
        call_command("seed_exams")
        for cycle in ExamCycle.objects.all():
            self.assertFalse(cycle.is_published)
            self.assertFalse(cycle.verified_by_human)

    def test_eligibility_source_url_present_when_numbers_present(self):
        call_command("seed_exams")
        for elig in ExamEligibility.objects.all():
            if (
                elig.min_age is not None
                or elig.max_age is not None
                or elig.attempts_general is not None
                or elig.attempts_obc is not None
                or elig.attempts_sc_st is not None
                or elig.attempts_pwbd is not None
            ):
                self.assertTrue(elig.source_url)
            # Special case: UPSC has explicit source, others may have empty source_url but no numbers
            # The constraint is: if any number is present, source_url must be non-empty
            # The seed provides source_url for all exams, even if no numbers, so this passes.

    def test_each_exam_has_short_name(self):
        call_command("seed_exams")
        for exam in Exam.objects.all():
            self.assertTrue(exam.short_name)
