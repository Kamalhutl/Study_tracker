"""Deterministic demo dataset covering every admin state (idempotent, DEBUG-only)."""

from argparse import ArgumentParser
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.companies import services as company_services
from apps.companies.enums import (
    CandidateOrigin,
    DetectionStatus,
    ScrapeHealth,
)
from apps.companies.models import CareerCandidateUrl, Company
from apps.jobs import services as job_services
from apps.jobs.enums import JobStatus, ReportReason
from apps.jobs.models import Job, JobReport
from core.utils import normalize_url


class Command(BaseCommand):
    help = "Create a deterministic demo dataset (ATS company, review queue, failures, all job statuses)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--actor-email", default="admin@example.com", help="Demo actor email")
        parser.add_argument(
            "--companies",
            type=int,
            default=10,
            help="Total companies (5 hand-crafted + bulk extras)",
        )
        parser.add_argument(
            "--jobs-per",
            type=int,
            default=8,
            help="Total jobs for the ATS company (6 hand-crafted + extras)",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG and not getattr(settings, "ALLOW_DEMO_SEED", False):
            raise CommandError(
                "seed_demo refuses to run when DEBUG is False (dangerous on prod-like data)."
            )

        actor = User.objects.filter(email=options["actor_email"]).first()
        if actor is None:
            actor = User.objects.create_user(
                email=options["actor_email"],
                password="demo-pass-123",
                is_staff=True,
                is_superuser=True,
            )

        if Company.all_objects.filter(slug="acme-robotics").exists():
            self.stdout.write("Demo data already present — nothing to do (idempotent).")
            return

        now = timezone.now()

        # 1. ATS-verified company (Case B path) — Greenhouse.
        acme = company_services.add_company_from_direct_career_url(
            name="Acme Robotics",
            career_url="https://boards.greenhouse.io/acmerobotics",
            actor=actor,
            industry="Robotics",
            size_bucket="200-500",
        )
        acme.scrape_health = ScrapeHealth.HEALTHY
        acme.save(update_fields=["scrape_health"])

        # 2. Custom-page company awaiting detection review with 3 candidates.
        custom = company_services.add_company_from_main_website(
            name="Burly Wood Custom", website_url="https://burlywoodcustom.example", actor=actor
        )
        custom.detection_status = DetectionStatus.NEEDS_REVIEW
        custom.save(update_fields=["detection_status"])
        for i, (url, origin, score) in enumerate(
            [
                ("https://burlywoodcustom.example/careers", CandidateOrigin.HEADER_LINK, 87),
                ("https://burlywoodcustom.example/jobs", CandidateOrigin.COMMON_PATH, 71),
                ("https://careers.burlywoodcustom.example", CandidateOrigin.SUBDOMAIN_GUESS, 43),
            ],
            start=1,
        ):
            CareerCandidateUrl.objects.create(
                company=custom,
                url=url,
                normalized_url=normalize_url(url),
                origin=origin,
                score=score,
                score_reasons=[{"rule": f"demo-rule-{i}", "points": score}],
                sample_job_titles=[f"Woodworker {i}", f"Finisher {i}"],
            )

        # 3. Failing company — 4 consecutive failures.
        failing = company_services.add_company_from_direct_career_url(
            name="Failing Co", career_url="https://failing.demo.example/careers", actor=actor
        )
        failing.scrape_health = ScrapeHealth.FAILING
        failing.consecutive_failures = 4
        failing.total_failures = 6
        failing.total_scrapes = 7
        failing.last_failure_reason = "demo — simulated repeated failures"
        failing.save(
            update_fields=[
                "scrape_health",
                "consecutive_failures",
                "total_failures",
                "total_scrapes",
                "last_failure_reason",
            ]
        )

        # 4. Paused company — needs a human.
        paused = company_services.add_company_from_direct_career_url(
            name="Paused Inc", career_url="https://paused.demo.example/careers", actor=actor
        )
        paused.scrape_health = ScrapeHealth.PAUSED
        paused.is_active = False
        paused.next_scrape_at = None
        paused.consecutive_failures = 5
        paused.save(
            update_fields=["scrape_health", "is_active", "next_scrape_at", "consecutive_failures"]
        )

        # 5. Jobs in every status.
        payloads = [
            {
                "title": "Senior Backend Engineer",
                "location_raw": "Remote",
                "description": "Python, Django, Postgres.",
            },
            {
                "title": "Frontend Engineer",
                "location_raw": "Remote",
                "description": "React and TypeScript.",
            },
            {
                "title": "DevOps Engineer",
                "location_raw": "Remote",
                "description": "Kubernetes, Terraform.",
            },
            {
                "title": "Product Designer",
                "location_raw": "Remote",
                "description": "Figma, design systems.",
            },
            {
                "title": "Growth Marketer",
                "location_raw": "Remote",
                "description": "SEO and lifecycle email.",
            },
            {
                "title": "Support Engineer",
                "location_raw": "Remote",
                "description": "Zendesk, Postgres.",
            },
        ]
        jobs: list[Job] = []
        for payload in payloads:
            job, _ = job_services.upsert_job(company=acme, payload=payload, actor=actor)
            jobs.append(job)

        for i in range(6, max(6, options["jobs_per"])):
            job, _ = job_services.upsert_job(
                company=acme,
                payload={
                    "title": f"Bulk Role {i}",
                    "location_raw": "Remote",
                    "description": f"Seeded bulk role number {i}.",
                },
                actor=actor,
            )
            jobs.append(job)

        # open + published, possibly_closed, likely_closed, closed via the ladder
        job_services.unpublish_job(job=jobs[0], actor=actor)
        job_services.publish_job(job=jobs[0], actor=actor)
        job_services.publish_job(job=jobs[1], actor=actor)
        job_services.publish_job(job=jobs[2], actor=actor)
        job_services.apply_missing_strikes(
            company=acme, seen_job_ids={jobs[0].id, jobs[1].id, jobs[2].id}
        )
        job_services.apply_missing_strikes(company=acme, seen_job_ids={jobs[0].id, jobs[1].id})
        job_services.apply_missing_strikes(company=acme, seen_job_ids={jobs[0].id})
        # jobs[3] now CLOSED, jobs[4] LIKELY_CLOSED, jobs[5] POSSIBLY_CLOSED

        Job.objects.create(
            company=acme,
            title="Draft Internship",
            source_url="https://boards.greenhouse.io/acmerobotics/draft-intern",
            normalized_source_url="https://boards.greenhouse.io/acmerobotics/draft-intern",
            content_hash="demo-draft-hash",
            title_normalized="draft internship",
            status=JobStatus.DRAFT,
        )

        # 6. Manually edited field.
        job_services.edit_job_fields(job=jobs[1], changes={"city": "Bengaluru"}, actor=actor)

        # 7. Duplicate pair.
        dup_job, _ = job_services.upsert_job(
            company=acme,
            payload={
                "title": "Backend Engineer (Senior)",
                "location_raw": "Remote",
                "description": "Python, Django, Postgres.",
            },
            actor=actor,
        )
        job_services.mark_duplicate(job=dup_job, canonical=jobs[0], actor=actor)

        # 8. Open report.
        JobReport.objects.create(
            job=jobs[2], user=actor, reason=ReportReason.EXPIRED, comment="Listing vanished."
        )

        # 9. A due-now, healthy custom company so the scheduler panel has work.
        due = company_services.add_company_from_direct_career_url(
            name="Due Now Co",
            career_url="https://boards.lever.co/duenow",
            actor=actor,
            description="Demo company that is due immediately.",
        )
        due.next_scrape_at = now - timedelta(minutes=5)
        due.save(update_fields=["next_scrape_at"])

        # 10. Bulk extras — deterministic simple companies, all due now.
        for i in range(5, max(5, options["companies"])):
            extra = company_services.add_company_from_direct_career_url(
                name=f"Bulk Co {i}",
                career_url=f"https://bulk-{i}.demo.example/careers",
                actor=actor,
                description="Seeded bulk company.",
            )
            extra.scrape_health = ScrapeHealth.HEALTHY
            extra.next_scrape_at = now - timedelta(minutes=5)
            extra.save(update_fields=["scrape_health", "next_scrape_at"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo data seeded: {options['companies']} companies, open/possibly/likely/closed/draft jobs "
                f"({options['jobs_per']} for the ATS company), a manual-edit job, a duplicate pair, "
                "and an open report. Re-running is a no-op."
            )
        )
