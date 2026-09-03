import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_report_requires_auth(client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    response = client.post(url, {"reason": "spam"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_report_created(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    response = authenticated_client.post(url, {"reason": "spam", "detail": "Test report"})
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["reason"] == "spam"
    assert response.data["detail"] == "Test report"
    assert response.data["status"] == "open"


@pytest.mark.django_db
def test_report_unique_open(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    authenticated_client.post(url, {"reason": "spam"})
    response = authenticated_client.post(url, {"reason": "broken_link"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_report_invalid_reason(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    response = authenticated_client.post(url, {"reason": "invalid"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_report_job_not_found(authenticated_client):
    url = reverse("jobs:job-report", args=["00000000-0000-0000-0000-000000000000"])
    response = authenticated_client.post(url, {"reason": "spam"})
    assert response.status_code == status.HTTP_404_NOT_FOUND
