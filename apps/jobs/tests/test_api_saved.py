import pytest
from django.urls import reverse
from rest_framework import status

from apps.jobs.models import SavedJob


@pytest.mark.django_db
def test_saved_jobs_requires_auth(client):
    url = reverse("jobs:job-saved")
    response = client.get(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_saved_jobs_list_empty(authenticated_client):
    url = reverse("jobs:job-saved")
    response = authenticated_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 0


@pytest.mark.django_db
def test_saved_jobs_annotation(authenticated_client, job_factory):
    user = authenticated_client.user
    job1 = job_factory(is_published=True, status="open")
    job_factory(is_published=True, status="open")
    from apps.jobs.services import save_job

    save_job(user=user, job=job1)
    # list jobs and check is_saved
    url = reverse("jobs:job-list")
    response = authenticated_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    saved_ids = [str(job1.pk)]
    for item in results:
        if item["id"] in saved_ids:
            assert item["is_saved"] is True
        else:
            assert item["is_saved"] is False


@pytest.mark.django_db
def test_is_saved_anonymous(client, job_factory):
    job_factory(is_published=True, status="open")
    url = reverse("jobs:job-list")
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["results"][0]["is_saved"] is False


@pytest.mark.django_db
def test_saved_job_duplicate_save_idempotent(authenticated_client, job_factory):
    user = authenticated_client.user
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-save", args=[job.pk])
    response1 = authenticated_client.post(url)
    assert response1.status_code == status.HTTP_200_OK
    response2 = authenticated_client.post(url)
    assert response2.status_code == status.HTTP_200_OK
    # only one saved job record
    assert SavedJob.objects.filter(user=user, job=job).count() == 1
