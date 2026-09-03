from datetime import timedelta
from urllib.parse import quote_plus

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status


@pytest.mark.django_db
def test_filter_work_mode(client, job_factory):
    job_factory(is_published=True, status="open", work_mode="remote")
    job_factory(is_published=True, status="open", work_mode="hybrid")
    url = reverse("jobs:job-list") + "?work_mode=remote"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["work_mode"] == "remote"


@pytest.mark.django_db
def test_filter_work_mode_multi(client, job_factory):
    job_factory(is_published=True, status="open", work_mode="remote")
    job_factory(is_published=True, status="open", work_mode="hybrid")
    job_factory(is_published=True, status="open", work_mode="onsite")
    url = reverse("jobs:job-list") + "?work_mode=remote,hybrid"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 2


@pytest.mark.django_db
def test_filter_job_type(client, job_factory):
    job_factory(is_published=True, status="open", job_type="full_time")
    job_factory(is_published=True, status="open", job_type="part_time")
    url = reverse("jobs:job-list") + "?job_type=full_time"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_company(client, job_factory, company_factory):
    company1 = company_factory(slug="acme")
    company2 = company_factory(slug="beta")
    job_factory(is_published=True, status="open", company=company1)
    job_factory(is_published=True, status="open", company=company2)
    url = reverse("jobs:job-list") + "?company=acme"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_department(client, job_factory):
    job_factory(is_published=True, status="open", department="Engineering")
    job_factory(is_published=True, status="open", department="Sales")
    url = reverse("jobs:job-list") + "?department=eng"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_location(client, job_factory):
    job_factory(is_published=True, status="open", location_raw="San Francisco")
    job_factory(is_published=True, status="open", location_raw="New York")
    url = reverse("jobs:job-list") + "?location=francisco"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_posted_after(client, job_factory):
    now = timezone.now().replace(microsecond=0)
    past = now - timedelta(days=5)
    job_factory(is_published=True, status="open", posted_at=past)
    job_factory(is_published=True, status="open", posted_at=now)
    url = reverse("jobs:job-list") + f"?posted_after={quote_plus(now.isoformat())}"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_posted_within_days(client, job_factory):
    now = timezone.now()
    past = now - timedelta(days=3)
    job_factory(is_published=True, status="open", posted_at=past)
    job_factory(is_published=True, status="open", posted_at=now - timedelta(days=10))
    url = reverse("jobs:job-list") + "?posted_within_days=5"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_has_apply_url(client, job_factory):
    job_factory(is_published=True, status="open", apply_url="http://example.com/apply")
    job_factory(is_published=True, status="open", apply_url="")
    url = reverse("jobs:job-list") + "?has_apply_url=true"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data["results"]) == 1


@pytest.mark.django_db
def test_filter_ordering(client, job_factory):
    job_factory(
        is_published=True,
        status="open",
        title="Alpha",
        posted_at=timezone.now() - timedelta(days=1),
    )
    job_factory(is_published=True, status="open", title="Beta", posted_at=timezone.now())
    url = reverse("jobs:job-list") + "?ordering=-posted_at"
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    results = response.data["results"]
    assert results[0]["posted_at"] > results[1]["posted_at"]


@pytest.mark.django_db
def test_ordering_invalid(client, job_factory):
    url = reverse("jobs:job-list") + "?ordering=invalid"
    response = client.get(url)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_order_null_posted_at_last(client, job_factory):
    job_factory(is_published=True, status="open", posted_at=None)
    job_factory(is_published=True, status="open", posted_at=timezone.now())
    url = reverse("jobs:job-list") + "?ordering=-posted_at"
    response = client.get(url)
    results = response.data["results"]
    # The job with posted_at should come first, the null last
    assert results[0]["posted_at"] is not None
    assert results[-1]["posted_at"] is None
