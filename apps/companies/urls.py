from django.urls import path

from apps.companies.views import CompanyDetailView, CompanyJobsView, CompanyListView

app_name = "companies"

urlpatterns = [
    path("", CompanyListView.as_view(), name="company-list"),
    path("<slug:slug>/", CompanyDetailView.as_view(), name="company-detail"),
    path("<slug:slug>/jobs/", CompanyJobsView.as_view(), name="company-jobs"),
]
