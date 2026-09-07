from django.contrib.postgres.indexes import GinIndex
from django.db import models

from core.models import SoftDeleteModel, TimeStampedModel, UUIDModel


class BodyType(models.TextChoices):
    CENTRAL = "central", "Central"
    STATE = "state", "State"
    BANKING = "banking", "Banking"
    RAILWAY = "railway", "Railway"
    DEFENCE = "defence", "Defence"
    TESTING_AGENCY = "testing_agency", "Testing Agency"


class ExamCategory(models.TextChoices):
    CIVIL_SERVICES = "civil_services", "Civil Services"
    BANKING = "banking", "Banking"
    RAILWAY = "railway", "Railway"
    SSC = "ssc", "SSC"
    TEACHING = "teaching", "Teaching"
    DEFENCE = "defence", "Defence"
    ENGINEERING = "engineering", "Engineering"
    MEDICAL = "medical", "Medical"
    LAW = "law", "Law"
    STATE_PSC = "state_psc", "State PSC"
    OTHER = "other", "Other"


class ExamLevel(models.TextChoices):
    NATIONAL = "national", "National"
    STATE = "state", "State"


class CycleStatus(models.TextChoices):
    ANNOUNCED = "announced", "Announced"
    NOTIFICATION_OUT = "notification_out", "Notification Out"
    APPLICATIONS_OPEN = "applications_open", "Applications Open"
    APPLICATIONS_CLOSED = "applications_closed", "Applications Closed"
    ADMIT_CARD_OUT = "admit_card_out", "Admit Card Out"
    EXAM_CONDUCTED = "exam_conducted", "Exam Conducted"
    RESULT_OUT = "result_out", "Result Out"
    CANCELLED = "cancelled", "Cancelled"
    POSTPONED = "postponed", "Postponed"


class StageMode(models.TextChoices):
    ONLINE_CBT = "online_cbt", "Online CBT"
    OFFLINE_OMR = "offline_omr", "Offline OMR"
    DESCRIPTIVE = "descriptive", "Descriptive"
    INTERVIEW = "interview", "Interview"
    PHYSICAL = "physical", "Physical"
    DOCUMENT = "document", "Document"


class ChangeDetectedBy(models.TextChoices):
    SCRAPE = "scrape", "Scrape"
    HUMAN = "human", "Human"
    CORRIGENDUM = "corrigendum", "Corrigendum"


class ConductingBody(UUIDModel, TimeStampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True)
    slug = models.SlugField(max_length=100, unique=True)
    body_type = models.CharField(max_length=20, choices=BodyType.choices)
    state = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "conducting bodies"
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="conductingbody_name_trgm"),
        ]

    def __str__(self) -> str:
        return self.name


class Exam(UUIDModel, TimeStampedModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True)
    slug = models.SlugField(max_length=100, unique=True)
    conducting_body = models.ForeignKey(
        ConductingBody, on_delete=models.PROTECT, related_name="exams"
    )
    category = models.CharField(max_length=20, choices=ExamCategory.choices)
    level = models.CharField(max_length=10, choices=ExamLevel.choices)
    description = models.TextField(blank=True)
    official_url = models.URLField(blank=True)
    typical_month = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=["category", "level"]),
            GinIndex(fields=["name"], opclasses=["gin_trgm_ops"], name="exam_name_trgm"),
        ]

    def __str__(self) -> str:
        return self.name


class ExamCycle(UUIDModel, TimeStampedModel, SoftDeleteModel):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="cycles")
    year = models.PositiveIntegerField()
    cycle_label = models.CharField(max_length=50)
    status = models.CharField(max_length=30, choices=CycleStatus.choices)
    notification_date = models.DateField(null=True, blank=True)
    application_start = models.DateField(null=True, blank=True)
    application_end = models.DateField(null=True, blank=True)
    fee_last_date = models.DateField(null=True, blank=True)
    correction_window_start = models.DateField(null=True, blank=True)
    correction_window_end = models.DateField(null=True, blank=True)
    result_date = models.DateField(null=True, blank=True)
    vacancy_count = models.PositiveIntegerField(null=True, blank=True)
    official_notification_url = models.URLField(blank=True)
    notification_pdf_url = models.URLField(blank=True)
    source_url = models.URLField(blank=True)
    extraction_confidence = models.PositiveSmallIntegerField(
        default=0,
    )
    verified_by_human = models.BooleanField(default=False)
    is_published = models.BooleanField(default=False)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("exam", "year", "cycle_label")]
        indexes = [
            models.Index(fields=["status", "-application_end"]),
            models.Index(fields=["is_published", "-notification_date"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(extraction_confidence__gte=0, extraction_confidence__lte=100),
                name="extraction_confidence_range",
            ),
            models.CheckConstraint(
                condition=models.Q(is_published=False) | models.Q(verified_by_human=True),
                name="examcycle_published_requires_verification",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.exam.name} {self.cycle_label}"


class ExamStage(UUIDModel, TimeStampedModel, SoftDeleteModel):
    cycle = models.ForeignKey(ExamCycle, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=100)
    stage_order = models.PositiveSmallIntegerField()
    mode = models.CharField(max_length=20, choices=StageMode.choices)
    date_start = models.DateField(null=True, blank=True)
    date_end = models.DateField(null=True, blank=True)
    is_date_tentative = models.BooleanField(default=True)
    admit_card_date = models.DateField(null=True, blank=True)
    city_intimation_date = models.DateField(null=True, blank=True)
    result_date = models.DateField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    total_marks = models.PositiveIntegerField(null=True, blank=True)
    negative_marking = models.TextField(blank=True)
    is_qualifying_only = models.BooleanField(default=False)

    class Meta:
        unique_together = [("cycle", "stage_order")]
        ordering = ["stage_order"]

    def __str__(self) -> str:
        return f"{self.cycle} - {self.name}"


class ExamEligibility(UUIDModel, TimeStampedModel, SoftDeleteModel):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="eligibility")
    cycle = models.ForeignKey(
        ExamCycle, null=True, blank=True, on_delete=models.CASCADE, related_name="eligibility"
    )
    min_age = models.PositiveSmallIntegerField(null=True, blank=True)
    max_age = models.PositiveSmallIntegerField(null=True, blank=True)
    age_as_on_date = models.DateField(null=True, blank=True)
    age_relaxation = models.JSONField(default=dict)
    attempts_general = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts_obc = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts_sc_st = models.PositiveSmallIntegerField(null=True, blank=True)
    attempts_pwbd = models.PositiveSmallIntegerField(null=True, blank=True)
    min_qualification = models.TextField(blank=True)
    allow_final_year_appearing = models.BooleanField(default=False)
    nationality_note = models.TextField(blank=True)
    physical_standards = models.JSONField(null=True, blank=True)
    verified_by_human = models.BooleanField(default=False)
    source_url = models.URLField(blank=True)

    class Meta:
        verbose_name_plural = "exam eligibility"

    def __str__(self) -> str:
        return f"Eligibility for {self.exam.name}"


class ExamDateChange(UUIDModel, TimeStampedModel, SoftDeleteModel):
    cycle = models.ForeignKey(ExamCycle, on_delete=models.CASCADE, related_name="date_changes")
    stage = models.ForeignKey(
        ExamStage, null=True, blank=True, on_delete=models.CASCADE, related_name="date_changes"
    )
    field_name = models.CharField(max_length=50)
    old_value = models.TextField()
    new_value = models.TextField()
    changed_at = models.DateTimeField(auto_now_add=True)
    source_url = models.URLField(blank=True)
    detected_by = models.CharField(max_length=20, choices=ChangeDetectedBy.choices)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-changed_at"]


class SavedExam(UUIDModel, TimeStampedModel, SoftDeleteModel):
    user = models.ForeignKey("accounts.User", on_delete=models.CASCADE, related_name="saved_exams")
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="saved_by")
    notify = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "exam")]

    def __str__(self) -> str:
        return f"{self.user} saved {self.exam.name}"
