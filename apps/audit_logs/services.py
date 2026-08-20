"""The one public audit API: ``record(...)``."""

import contextvars
import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from .models import AuditLog, Source

logger = logging.getLogger("study_tracker.audit")

# Context set by AuditContextMiddleware: actor, ip, request_id.
_actor_var: contextvars.ContextVar[Any] = contextvars.ContextVar("audit_actor", default=None)
_ip_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("audit_ip", default=None)
_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "audit_request_id", default=""
)


def _jsonable(value: Any) -> Any:
    """Recursively turn anything into JSON-safe values."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_jsonable(item) for item in value]
    if isinstance(value, UUID | Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "pk") and hasattr(value, "__str__"):  # model instance
        return {"id": str(value.pk), "repr": str(value)}
    return value


def snapshot(instance: Any, fields: Iterable[str] | None = None) -> dict[str, Any]:
    """JSON-safe snapshot of a model instance (or dict)."""
    if instance is None:
        return {}
    if isinstance(instance, Mapping):
        return {str(k): _jsonable(v) for k, v in instance.items()}
    chosen = list(fields) if fields is not None else None
    data: dict[str, Any] = {}
    for field in instance._meta.fields:
        if chosen is not None and field.name not in chosen:
            continue
        if field.name == "password":
            continue
        if not hasattr(instance, field.name):
            continue
        data[field.name] = _jsonable(getattr(instance, field.name))
    return data


def _diff_fields(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> list[str]:
    before = before or {}
    after = after or {}
    keys = set(before) | set(after)
    return sorted(key for key in keys if before.get(key) != after.get(key))


def record(
    action: str,
    *,
    actor: Any = None,
    instance: Any = None,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    source: str = Source.SYSTEM,
    request: Any = None,
    **extra: Any,
) -> AuditLog | None:
    """Write an audit log row. Safe inside transactions and Celery tasks.

    Never raises into the caller: internal failures are logged and None is
    returned. Actor/ip/request_id are auto-filled from the request context
    (middleware contextvars) when not given explicitly.
    """
    try:
        if before is None and instance is not None and after is not None:
            before = snapshot(instance)
        changed = _diff_fields(before, after)

        actor_label = ""
        if actor is not None:
            try:
                actor_label = getattr(actor, "actor_label", None) or str(actor)
            except Exception:
                actor_label = str(actor)

        meta = getattr(instance, "_meta", None) if instance is not None else None
        app_label = meta.app_label if meta is not None else ""
        model_name = meta.model_name if meta is not None else ""
        object_id = (
            str(getattr(instance, "pk", None))
            if instance is not None and getattr(instance, "pk", None)
            else ""
        )
        object_repr = str(instance) if instance is not None else ""

        if actor is None:
            actor = _actor_var.get()
        ip = _ip_var.get()
        request_id = _request_id_var.get()
        if request is not None:
            ip = getattr(request, "client_ip", None) or request.META.get("REMOTE_ADDR", "")
            request_id = getattr(request, "request_id", "") or request_id

        entry = AuditLog.objects.create(
            actor=actor,
            actor_label=actor_label,
            action=action,
            app_label=app_label,
            model_name=model_name,
            object_id=object_id,
            object_repr=object_repr,
            before=_jsonable(before) if before is not None else None,
            after=_jsonable(after) if after is not None else None,
            changed_fields=changed,
            source=source,
            ip=ip,
            request_id=request_id,
            **extra,
        )
        return entry
    except Exception:
        logger.exception("AuditLog.record failed for action=%s", action)
        return None
