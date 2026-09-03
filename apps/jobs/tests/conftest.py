import uuid

import pytest
from rest_framework.test import APIClient

from apps.companies.models import Company
from apps.jobs.models import Job
from tests.factories import UserFactory


@pytest.fixture
def user():
    return UserFactory()


@pytest.fixture
def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def company_factory():
    def _factory(**kwargs):
        if "added_by" not in kwargs:
            kwargs["added_by"] = UserFactory()
        if "domain" not in kwargs:
            kwargs["domain"] = f"{kwargs.get('slug', 'test')}.com"
        if "name" not in kwargs:
            kwargs["name"] = kwargs.get("slug", "Test Company")
        if "input_type" not in kwargs:
            kwargs["input_type"] = "manual"
        if "input_url" not in kwargs:
            kwargs["input_url"] = f"http://{kwargs['domain']}"
        return Company.objects.create(**kwargs)

    return _factory


@pytest.fixture
def job_factory():
    def _factory(**kwargs):
        if "company" not in kwargs:
            slug = f"test-company-{uuid.uuid4().hex[:8]}"
            company = Company.objects.create(
                name="Test Company",
                slug=slug,
                domain=f"{slug}.com",
                input_type="manual",
                input_url=f"http://{slug}.com",
                added_by=UserFactory(),
            )
            kwargs["company"] = company
        return Job.objects.create(**kwargs)

    return _factory
