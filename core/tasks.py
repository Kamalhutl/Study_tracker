from celery import shared_task


@shared_task
def ping() -> str:
    """Liveness task returning a literal string (used by tests / ops)."""
    return "pong"
