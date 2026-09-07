from django.contrib import admin

from apps.companies.admin_site import ops_site

from .models import (
    ConductingBody,
    Exam,
    ExamCycle,
    ExamDateChange,
    ExamEligibility,
    ExamStage,
    SavedExam,
)


@admin.register(ConductingBody, site=ops_site)
class ConductingBodyAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "slug", "body_type", "is_active")
    search_fields = ("name", "short_name", "slug")
    list_filter = ("body_type", "is_active")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Exam, site=ops_site)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "conducting_body", "category", "level", "is_active")
    search_fields = ("name", "short_name", "slug")
    list_filter = ("category", "level", "is_active")
    list_select_related = ("conducting_body",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(ExamCycle, site=ops_site)
class ExamCycleAdmin(admin.ModelAdmin):
    list_display = ("exam", "year", "cycle_label", "status", "application_end", "is_published")
    search_fields = ("exam__name", "cycle_label")
    list_filter = ("status", "is_published", "verified_by_human")
    list_select_related = ("exam", "exam__conducting_body")
    date_hierarchy = "notification_date"


@admin.register(ExamStage, site=ops_site)
class ExamStageAdmin(admin.ModelAdmin):
    list_display = ("cycle", "name", "stage_order", "mode", "date_start", "date_end")
    search_fields = ("name", "cycle__exam__name")
    list_filter = ("mode", "is_qualifying_only")
    list_select_related = ("cycle", "cycle__exam")


@admin.register(ExamEligibility, site=ops_site)
class ExamEligibilityAdmin(admin.ModelAdmin):
    list_display = ("exam", "min_age", "max_age", "verified_by_human")
    search_fields = ("exam__name",)
    list_filter = ("verified_by_human",)
    list_select_related = ("exam",)


@admin.register(ExamDateChange, site=ops_site)
class ExamDateChangeAdmin(admin.ModelAdmin):
    list_display = ("cycle", "field_name", "detected_by", "changed_at")
    search_fields = ("cycle__exam__name", "field_name")
    list_filter = ("detected_by",)
    list_select_related = ("cycle", "cycle__exam")


@admin.register(SavedExam, site=ops_site)
class SavedExamAdmin(admin.ModelAdmin):
    list_display = ("user", "exam", "notify", "created_at")
    search_fields = ("user__email", "exam__name")
    list_filter = ("notify",)
    list_select_related = ("user", "exam")
