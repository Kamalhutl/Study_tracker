from django.db.models import Q
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, permissions, status
from rest_framework.filters import OrderingFilter
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.exams.filters import ExamFilter
from apps.exams.models import Exam, ExamCycle, SavedExam
from apps.exams.serializers import (
    CalendarEventSerializer,
    ExamCycleSerializer,
    ExamDetailSerializer,
    ExamListSerializer,
)
from core.pagination import CursorAwarePageNumberPagination


class ExamListView(generics.ListAPIView):
    queryset = Exam.objects.filter(is_active=True).select_related("conducting_body")
    serializer_class = ExamListSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ExamFilter
    ordering_fields = ["name", "created_at"]
    ordering = ["name"]
    pagination_class = CursorAwarePageNumberPagination
    permission_classes = [permissions.AllowAny]


class ExamDetailView(generics.RetrieveAPIView):
    queryset = Exam.objects.filter(is_active=True).prefetch_related(
        "cycles", "cycles__stages", "cycles__date_changes", "eligibility"
    )
    serializer_class = ExamDetailSerializer
    lookup_field = "slug"
    permission_classes = [permissions.AllowAny]


class ExamCycleListView(generics.ListAPIView):
    queryset = ExamCycle.objects.filter(is_published=True).select_related("exam")
    serializer_class = ExamCycleSerializer
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_fields = ["exam", "status", "year"]
    ordering_fields = ["application_start", "notification_date"]
    ordering = ["-notification_date"]
    pagination_class = CursorAwarePageNumberPagination
    permission_classes = [permissions.AllowAny]


class ExamCycleDetailView(generics.RetrieveAPIView):
    queryset = ExamCycle.objects.filter(is_published=True).prefetch_related(
        "stages", "date_changes"
    )
    serializer_class = ExamCycleSerializer
    lookup_field = "id"
    permission_classes = [permissions.AllowAny]


class CalendarView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = CalendarEventSerializer
    pagination_class = None

    def get_queryset(self):
        from datetime import datetime, timedelta

        from apps.exams.models import ExamCycle

        # Build flat events
        events = []
        start_date = self.request.query_params.get("from")
        end_date = self.request.query_params.get("to")
        if not start_date:
            start_date = timezone.now().date()
        else:
            start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        if not end_date:
            end_date = start_date + timedelta(days=90)
        else:
            end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

        cycles = (
            ExamCycle.objects.filter(
                Q(is_published=True)
                & (
                    Q(notification_date__gte=start_date, notification_date__lte=end_date)
                    | Q(application_start__gte=start_date, application_start__lte=end_date)
                    | Q(application_end__gte=start_date, application_end__lte=end_date)
                    | Q(fee_last_date__gte=start_date, fee_last_date__lte=end_date)
                    | Q(
                        correction_window_start__gte=start_date,
                        correction_window_start__lte=end_date,
                    )
                    | Q(correction_window_end__gte=start_date, correction_window_end__lte=end_date)
                    | Q(result_date__gte=start_date, result_date__lte=end_date)
                    | Q(stages__date_start__gte=start_date, stages__date_start__lte=end_date)
                    | Q(
                        stages__admit_card_date__gte=start_date,
                        stages__admit_card_date__lte=end_date,
                    )
                    | Q(stages__result_date__gte=start_date, stages__result_date__lte=end_date)
                )
            )
            .select_related("exam")
            .distinct()
        )

        for cycle in cycles:
            exam = cycle.exam

            def add_event(date, event_type, stage_name=None, is_tentative=False):
                if date is not None and start_date <= date <= end_date:
                    events.append(
                        {
                            "date": date,
                            "event_type": event_type,
                            "exam_name": exam.name,
                            "exam_slug": exam.slug,
                            "cycle_label": cycle.cycle_label,
                            "stage_name": stage_name,
                            "is_tentative": is_tentative,
                            "official_url": cycle.official_notification_url or exam.official_url,
                        }
                    )

            add_event(cycle.notification_date, "notification")
            add_event(cycle.application_start, "application_start")
            add_event(cycle.application_end, "application_end")
            add_event(cycle.fee_last_date, "fee_last_date")
            add_event(cycle.correction_window_start, "correction_start")
            add_event(cycle.correction_window_end, "correction_end")
            add_event(cycle.result_date, "result")
            for stage in cycle.stages.all():
                add_event(stage.date_start, "stage_exam", stage.name, stage.is_date_tentative)
                add_event(stage.admit_card_date, "admit_card", stage.name, stage.is_date_tentative)
                add_event(stage.result_date, "stage_result", stage.name, stage.is_date_tentative)

        # Sort by date
        events.sort(key=lambda x: x["date"])
        return events


class SaveExamView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, slug):
        exam = generics.get_object_or_404(Exam, slug=slug)
        saved, created = SavedExam.objects.get_or_create(user=request.user, exam=exam)
        return Response({"saved": True, "created": created}, status=status.HTTP_200_OK)

    def delete(self, request, slug):
        exam = generics.get_object_or_404(Exam, slug=slug)
        deleted = SavedExam.objects.filter(user=request.user, exam=exam).delete()
        return Response({"saved": False, "deleted": deleted > 0}, status=status.HTTP_200_OK)


class SavedExamListView(generics.ListAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ExamListSerializer
    pagination_class = CursorAwarePageNumberPagination

    def get_queryset(self):
        return Exam.objects.filter(saved_by__user=self.request.user, is_active=True)
