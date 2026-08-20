"""Print companies currently due for scraping — scheduler sanity check (read-only)."""

import json
from argparse import ArgumentParser
from typing import Any

from django.core.management.base import BaseCommand

from apps.companies.models import Company


class Command(BaseCommand):
    help = "List companies due for scraping (read-only scheduler sanity check)."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args: Any, **options: Any) -> None:
        rows = [
            {
                "id": str(c.id),
                "name": c.name,
                "career_url": c.career_url,
                "source_type": c.career_source_type,
                "next_scrape_at": c.next_scrape_at.isoformat() if c.next_scrape_at else None,
                "health": c.scrape_health,
            }
            for c in Company.objects.due()[: options["limit"]]
        ]
        if options["as_json"]:
            self.stdout.write(json.dumps(rows, indent=2))
            return
        if not rows:
            self.stdout.write("No companies due right now.")
            return
        keys = ("name", "career_url", "source_type", "next_scrape_at", "health")
        headers = tuple(k.upper() for k in keys)
        widths = [
            max(len(str(r[k])) for r in [*rows, dict(zip(keys, headers, strict=False))])
            for k in keys
        ]
        fmt = "  ".join(f"{{:<{w}}}" for w in widths)
        self.stdout.write(fmt.format(*headers))
        for r in rows:
            self.stdout.write(fmt.format(*(str(r[k]) for k in keys)))
