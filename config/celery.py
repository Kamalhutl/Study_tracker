"""Celery application wiring for study_tracker."""

from celery import Celery
from celery.app.task import Task

app = Celery("study_tracker")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)  # type: ignore[untyped-decorator]
def debug_task(self: Task) -> None:  # pragma: no cover - manual debug helper
    print(f"Request: {self.request!r}")
