from django.urls import path

from apps.exams import views

urlpatterns = [
    path("", views.ExamListView.as_view(), name="exam-list"),
    path("cycles/", views.ExamCycleListView.as_view(), name="cycle-list"),
    path("cycles/<uuid:id>/", views.ExamCycleDetailView.as_view(), name="cycle-detail"),
    path("calendar/", views.CalendarView.as_view(), name="calendar"),
    path("saved/", views.SavedExamListView.as_view(), name="saved-exams"),
    path("<slug:slug>/", views.ExamDetailView.as_view(), name="exam-detail"),
    path("<slug:slug>/save/", views.SaveExamView.as_view(), name="save-exam"),
]
