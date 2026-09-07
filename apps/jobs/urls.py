from django.urls import path

from apps.jobs.views import (
    JobDetailBySlugView,
    JobDetailView,
    JobFacetsView,
    JobListView,
    ReportJobView,
    SavedJobListView,
    SaveJobView,
)

app_name = "jobs"

urlpatterns = [
    path("", JobListView.as_view(), name="job-list"),
    path("<uuid:pk>/", JobDetailView.as_view(), name="job-detail"),
    path("by-slug/<slug:slug>/", JobDetailBySlugView.as_view(), name="job-detail-slug"),
    path("<uuid:pk>/save/", SaveJobView.as_view(), name="job-save"),
    path("saved/", SavedJobListView.as_view(), name="job-saved"),
    path("<uuid:pk>/report/", ReportJobView.as_view(), name="job-report"),
    path("facets/", JobFacetsView.as_view(), name="job-facets"),
]
