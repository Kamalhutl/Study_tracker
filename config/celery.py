from __future__ import annotations

from typing import Any

from celery import Celery
from celery.app.task import Task
from celery.schedules import crontab

"""Celery application wiring for study_tracker."""

app = Celery("study_tracker")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "scrape-verified-companies": {
        "task": "scraping.tasks.refresh_all_companies",
        "schedule": crontab(hour="*/5", minute="2"),
        "options": {"queue": "scraping"},
    },
}


@app.task(bind=True)
def debug_task(self: Task[Any, Any]) -> None:  # pragma: no cover - manual debug helper
    print(f"Request: {self.request!r}")
