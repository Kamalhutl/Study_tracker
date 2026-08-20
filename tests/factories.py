import uuid
from typing import Any

import factory
from django.contrib.auth import get_user_model
from django.utils import timezone


def _e164_phone() -> str:
    return f"+9199{uuid.uuid4().hex[:10]}"


class UserFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = get_user_model()

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    password = factory.PostGenerationMethodCall("set_password", "str0ng-Password!")
    full_name = factory.Faker("name")
    phone = factory.LazyFunction(_e164_phone)
    role = "user"
    is_active = True


class AdminUserFactory(UserFactory):
    role = "admin"
    is_staff = True
    is_superuser = True


# --- companies -------------------------------------------------------------


class CompanyFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "companies.Company"

    name = factory.Sequence(lambda n: f"Company {n}")
    slug = factory.Sequence(lambda n: f"company-{n}")
    domain = factory.Sequence(lambda n: f"company{n}.example")
    input_type = "direct_career"
    input_url = factory.LazyAttribute(lambda o: f"https://{o.domain}/careers")
    added_by = factory.SubFactory(AdminUserFactory)
    career_url = factory.LazyAttribute(lambda o: f"https://{o.domain}/careers")
    career_source_type = "own_career_page"
    detection_status = "skipped"
    is_verified = True
    next_scrape_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(hours=1))

    class Params:
        ats = factory.Trait(career_source_type="greenhouse", ats_identifier="acme")
        needs_review = factory.Trait(
            detection_status="needs_review", is_verified=False, career_url=""
        )
        failing = factory.Trait(scrape_health="failing", consecutive_failures=4)
        paused = factory.Trait(scrape_health="paused", is_active=False, next_scrape_at=None)
        case_a = factory.Trait(
            input_type="main_website",
            detection_status="pending",
            is_verified=False,
            career_url="",
        )


class CompanySourceFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "companies.CompanySource"

    company = factory.SubFactory(CompanyFactory)
    url = factory.Sequence(lambda n: f"https://sources{n}.example/careers")
    normalized_url = factory.LazyAttribute(lambda o: o.url)
    source_type = "own_career_page"
    is_current = True


class CandidateFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "companies.CareerCandidateUrl"

    company = factory.SubFactory(CompanyFactory)
    url = factory.Sequence(lambda n: f"https://candidate{n}.example/careers")
    normalized_url = factory.LazyAttribute(lambda o: o.url)
    origin = "header_link"
    score = 80


class DetectionRunFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "companies.DetectionRun"

    company = factory.SubFactory(CompanyFactory)
    status = "running"


# --- jobs -------------------------------------------------------------------


class JobFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "jobs.Job"

    company = factory.SubFactory(CompanyFactory)
    title = factory.Sequence(lambda n: f"Software Engineer {n}")
    title_normalized = factory.LazyAttribute(lambda o: o.title.lower())
    source_url = factory.Sequence(lambda n: f"https://jobs.example/postings/{n}")
    normalized_source_url = factory.LazyAttribute(lambda o: o.source_url)
    content_hash = factory.Sequence(lambda n: f"hash{n:040d}")
    status = "open"
    is_published = True

    class Params:
        stale = factory.Trait(status="possibly_closed", missing_count=1)
        likely_closed = factory.Trait(status="likely_closed", missing_count=2)
        closed = factory.Trait(status="closed", closed_at=factory.LazyFunction(timezone.now))
        draft = factory.Trait(status="draft", is_published=False)
        pending_review = factory.Trait(needs_review=True, is_published=False)
        manual_status = factory.Trait(is_manual_status=True)


class SavedJobFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "jobs.SavedJob"

    user = factory.SubFactory(UserFactory)
    job = factory.SubFactory(JobFactory)


class JobReportFactory(factory.django.DjangoModelFactory[Any]):
    class Meta:
        model = "jobs.JobReport"

    job = factory.SubFactory(JobFactory)
    user = factory.SubFactory(UserFactory)
    reason = "expired"
