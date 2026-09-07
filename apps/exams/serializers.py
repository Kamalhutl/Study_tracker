from typing import Any

from rest_framework import serializers

from apps.exams.models import (
    ConductingBody,
    Exam,
    ExamCycle,
    ExamDateChange,
    ExamEligibility,
    ExamStage,
)


class ConductingBodySerializer(serializers.ModelSerializer[ConductingBody]):
    class Meta:
        model = ConductingBody
        fields = ["id", "name", "short_name", "slug", "body_type", "state", "website", "is_active"]


class ExamStageSerializer(serializers.ModelSerializer[ExamStage]):
    class Meta:
        model = ExamStage
        fields = [
            "id",
            "name",
            "stage_order",
            "mode",
            "date_start",
            "date_end",
            "is_date_tentative",
            "admit_card_date",
            "city_intimation_date",
            "result_date",
            "duration_minutes",
            "total_marks",
            "negative_marking",
            "is_qualifying_only",
        ]


class ExamDateChangeSerializer(serializers.ModelSerializer[ExamDateChange]):
    class Meta:
        model = ExamDateChange
        fields = ["field_name", "old_value", "new_value", "changed_at", "detected_by", "note"]


class ExamCycleSerializer(serializers.ModelSerializer[ExamCycle]):
    stages = ExamStageSerializer(many=True, read_only=True)
    date_changes = ExamDateChangeSerializer(many=True, read_only=True)

    class Meta:
        model = ExamCycle
        fields = [
            "id",
            "year",
            "cycle_label",
            "status",
            "notification_date",
            "application_start",
            "application_end",
            "fee_last_date",
            "correction_window_start",
            "correction_window_end",
            "result_date",
            "vacancy_count",
            "official_notification_url",
            "notification_pdf_url",
            "source_url",
            "extraction_confidence",
            "verified_by_human",
            "is_published",
            "notes",
            "stages",
            "date_changes",
        ]


class ExamEligibilitySerializer(serializers.ModelSerializer[ExamEligibility]):
    class Meta:
        model = ExamEligibility
        fields = [
            "min_age",
            "max_age",
            "age_as_on_date",
            "age_relaxation",
            "attempts_general",
            "attempts_obc",
            "attempts_sc_st",
            "attempts_pwbd",
            "min_qualification",
            "allow_final_year_appearing",
            "nationality_note",
            "physical_standards",
            "verified_by_human",
        ]


class ExamListSerializer(serializers.ModelSerializer[Exam]):
    conducting_body = ConductingBodySerializer(read_only=True)
    latest_cycle_status = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = [
            "id",
            "slug",
            "name",
            "short_name",
            "conducting_body",
            "category",
            "level",
            "official_url",
            "typical_month",
            "is_active",
            "latest_cycle_status",
        ]

    def get_latest_cycle_status(self, obj: Exam) -> str | None:
        cycle = obj.cycles.filter(is_published=True).order_by("-year", "-created_at").first()
        return cycle.status if cycle else None


class ExamDetailSerializer(serializers.ModelSerializer[Exam]):
    conducting_body = ConductingBodySerializer(read_only=True)
    cycles = ExamCycleSerializer(many=True, read_only=True)
    eligibility = ExamEligibilitySerializer(many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            "id",
            "slug",
            "name",
            "short_name",
            "conducting_body",
            "category",
            "level",
            "description",
            "official_url",
            "typical_month",
            "is_active",
            "cycles",
            "eligibility",
        ]


class CalendarEventSerializer(serializers.Serializer[dict[str, Any]]):
    date = serializers.DateField()
    event_type = serializers.CharField()
    exam_name = serializers.CharField()
    exam_slug = serializers.SlugField()
    cycle_label = serializers.CharField()
    stage_name = serializers.CharField(allow_null=True)
    is_tentative = serializers.BooleanField()
    official_url = serializers.URLField(allow_blank=True)


class SaveExamSerializer(serializers.Serializer[dict[str, Any]]):
    exam_slug = serializers.SlugField()

    def validate_exam_slug(self, value: str) -> str:
        if not Exam.objects.filter(slug=value).exists():
            raise serializers.ValidationError("Exam not found")
        return value
