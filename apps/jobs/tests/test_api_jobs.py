import pytest
from django.urls import reverse
from rest_framework import status


@pytest.mark.django_db
def test_job_list_anonymous(client, job_factory):
    job_factory(is_published=True, status="open")
    url = reverse("jobs:job-list")
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] >= 1
    assert "results" in response.data


@pytest.mark.django_db
def test_job_list_pagination(client, job_factory):
    for _ in range(25):
        job_factory(is_published=True, status="open")
    url = reverse("jobs:job-list") + "?page_size=20"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 20
    assert response.data["count"] == 25


@pytest.mark.django_db
def test_job_detail_anonymous(client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-detail", args=[job.pk])
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["id"] == str(job.pk)


@pytest.mark.django_db
def test_job_detail_not_found(client):
    url = reverse("jobs:job-detail", args=["00000000-0000-0000-0000-000000000000"])
    response = client.get(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_job_save_requires_auth(client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-save", args=[job.pk])
    response = client.post(url)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_job_save_idempotent(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-save", args=[job.pk])
    response = authenticated_client.post(url)
    assert response.status_code == status.HTTP_200_OK
    response2 = authenticated_client.post(url)
    assert response2.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_job_unsave(authenticated_client, job_factory):
    user = authenticated_client.user
    job = job_factory(is_published=True, status="open")
    from apps.jobs.services import save_job

    save_job(user=user, job=job)
    url = reverse("jobs:job-save", args=[job.pk])
    response = authenticated_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_job_unsave_not_saved(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-save", args=[job.pk])
    response = authenticated_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
def test_job_save_404(authenticated_client):
    url = reverse("jobs:job-save", args=["00000000-0000-0000-0000-000000000000"])
    response = authenticated_client.post(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_saved_jobs_list(authenticated_client, job_factory):
    user = authenticated_client.user
    job1 = job_factory(is_published=True, status="open")
    job2 = job_factory(is_published=True, status="open")
    from apps.jobs.services import save_job

    save_job(user=user, job=job1)
    save_job(user=user, job=job2)
    url = reverse("jobs:job-saved")
    response = authenticated_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert response.data["count"] == 2


@pytest.mark.django_db
def test_job_report_requires_auth(client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    response = client.post(url, {"reason": "spam"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
def test_job_report_created(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    response = authenticated_client.post(url, {"reason": "spam", "detail": "test"})
    assert response.status_code == status.HTTP_201_CREATED
    assert response.data["reason"] == "spam"


@pytest.mark.django_db
def test_job_report_unique(authenticated_client, job_factory):
    job = job_factory(is_published=True, status="open")
    url = reverse("jobs:job-report", args=[job.pk])
    authenticated_client.post(url, {"reason": "spam"})
    response2 = authenticated_client.post(url, {"reason": "spam"})
    assert response2.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_job_facets_anonymous(client, job_factory):
    job_factory(is_published=True, status="open", work_mode="remote", job_type="full_time")
    url = reverse("jobs:job-facets")
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert "work_mode" in response.data
    assert response.data["work_mode"]["remote"] >= 1
