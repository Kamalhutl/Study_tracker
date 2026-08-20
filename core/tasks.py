from celery import shared_task


@shared_task  # type: ignore[untyped-decorator]
def ping() -> str:
    """Liveness task returning a literal string (used by tests / ops)."""
    return "pong"
