"""Rebuild Job search vectors (full or per-company). Maintenance helper."""

from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from apps.companies.models import Company
from apps.jobs import services as job_services


class Command(BaseCommand):
    help = "Recompute search_vector for all (or one company's) jobs."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--company", help="Limit to one company slug")

    def handle(self, *args: Any, **options: Any) -> None:
        if company_slug := options.get("company"):
            company = Company.objects.filter(slug=company_slug).first()
            if company is None:
                self.stderr.write(f"No company with slug {company_slug!r}.")
                return
            job_services.refresh_search_vector(company=company)
            count = company.jobs.filter(is_deleted=False).count()
            self.stdout.write(f"Rebuilt search vectors for {count} jobs of {company.name}.")
            return
        job_services.refresh_search_vector()
        self.stdout.write("Rebuilt search vectors for all jobs.")
