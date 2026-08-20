"""Audit log core: service API, middleware context, admin actions."""

import logging

from django.contrib.auth import get_user_model
from django.test import RequestFactory

from apps.accounts.admin import UserAdmin
from apps.audit_logs.models import AuditLog, Source
from apps.audit_logs.services import record, snapshot
from tests.factories import UserFactory

User = get_user_model()


def _admin_request(user, path="/admin/"):
    from django.contrib.messages.storage.fallback import FallbackStorage

    factory = RequestFactory()
    request = factory.get(path)
    request.user = user
    request.request_id = "admin-op"
    request.META["REMOTE_ADDR"] = "127.0.0.1"
    request.session = {}
    request._messages = FallbackStorage(request)
    return request


def test_record_creates_entry_with_diff_and_denormalized_actor(user, admin_user):
    entry = record(
        "user.deactivated",
        actor=admin_user,
        instance=user,
        before={"is_active": True},
        after={"is_active": False},
        source="ADMIN",
    )
    assert entry is not None
    assert entry.action == "user.deactivated"
    assert entry.actor == admin_user
    assert entry.actor_label == f"{admin_user.email} (admin)"
    assert entry.app_label == "accounts"
    assert entry.model_name == "user"
    assert entry.object_id == str(user.id)
    assert entry.object_repr == user.email
    assert entry.changed_fields == ["is_active"]
    assert entry.before == {"is_active": True}
    assert entry.after == {"is_active": False}
    assert entry.source == Source.ADMIN


def test_record_auto_snapshots_before_when_instance_given(user):
    entry = record(
        "user.updated",
        instance=user,
        after={"full_name": "Snapshotted"},
        source="SYSTEM",
    )
    assert entry is not None
    assert entry.before["email"] == user.email
    assert entry.before["role"] == "user"
    assert "password" not in entry.before


def test_record_never_raises_on_broken_instance(caplog):
    class Broken:
        @property
        def pk(self):
            return "X"

        def __str__(self) -> str:
            raise RuntimeError("broken __str__")

        @property
        def _meta(self):
            raise AttributeError("no meta")

        @property  # type: ignore[misc]  # pragma: no cover
        def __class__(self):
            return type(self)

    with caplog.at_level(logging.ERROR, logger="study_tracker.audit"):
        result = record("user.broken", instance=Broken(), source="SYSTEM")
    assert result is None
    assert any("AuditLog.record failed" in r.getMessage() for r in caplog.records)
    # Nothing half-created.
    assert AuditLog.objects.filter(action="user.broken").count() == 0


def test_snapshot_serializes_uuids_datetimes_decimals(user):
    data = snapshot(user)
    assert data["id"] == str(user.id)
    assert data["created_at"] == user.created_at.isoformat()
    assert data["years_of_experience"] is None or isinstance(
        data["years_of_experience"], str | int | float
    )


def test_snapshot_with_selected_fields(user):
    data = snapshot(user, fields=["email", "role"])
    assert set(data.keys()) == {"email", "role"}
    assert data["email"] == user.email


def test_jsonable_handles_nested_models_and_sets(user):
    from apps.audit_logs.services import _jsonable

    out = _jsonable({"owner": user, "tags": {"a", "b"}})
    assert out["owner"]["id"] == str(user.id)
    assert out["owner"]["repr"] == user.email
    assert set(out["tags"]) == {"a", "b"}


def test_record_fills_context_from_request_middleware(user):
    """AuditContextMiddleware plants actor/ip/request_id; record() uses them."""
    from apps.audit_logs.services import _actor_var, _ip_var, _request_id_var

    token_a = _actor_var.set(user)
    token_i = _ip_var.set("10.0.0.7")
    token_r = _request_id_var.set("req-xyz")
    try:
        entry = record("user.context_test", instance=user, source="API")
    finally:
        _actor_var.reset(token_a)
        _ip_var.reset(token_i)
        _request_id_var.reset(token_r)
    assert entry is not None
    assert entry.actor == user
    assert entry.ip == "10.0.0.7"
    assert entry.request_id == "req-xyz"


def test_admin_action_deactivate_users_audits_each(user, admin_user):
    second = UserFactory()
    request = _admin_request(admin_user)
    request.request_id = "admin-op-1"

    UserAdmin(User, None).deactivate_users(
        request, User.objects.filter(pk__in=[user.pk, second.pk])
    )

    user.refresh_from_db()
    second.refresh_from_db()
    assert user.is_active is False and second.is_active is False
    logs = AuditLog.objects.filter(action="user.deactivated")
    assert logs.count() == 2
    for user_obj in (user, second):
        log = logs.get(object_id=str(user_obj.id))
        assert log.actor == admin_user
        assert log.actor_label == f"{admin_user.email} (admin)"
        assert log.changed_fields == ["is_active"]
        assert log.source == Source.ADMIN
        assert log.request_id == "admin-op-1"


def test_admin_action_mark_email_verified(user):
    request = _admin_request(user)
    request.request_id = "admin-op-2"

    UserAdmin(User, None).mark_email_verified(request, User.objects.filter(pk=user.pk))
    user.refresh_from_db()
    assert user.email_verified_at is not None
    log = AuditLog.objects.get(action="user.email_verified")
    assert log.actor == user
    assert log.changed_fields == ["email_verified_at"]
    assert log.source == Source.ADMIN


def test_audit_admin_is_read_only():
    from apps.audit_logs.admin import AuditLogAdmin

    admin = AuditLogAdmin(AuditLog, None)
    assert admin.has_add_permission(None) is False
    assert admin.has_change_permission(None) is False
    assert admin.has_delete_permission(None) is False


def test_admin_action_deactivate_is_idempotent(user, admin_user):
    request = _admin_request(admin_user)
    request.request_id = "admin-op-3"

    admin = UserAdmin(User, None)
    admin.deactivate_users(request, User.objects.filter(pk=user.pk))
    assert AuditLog.objects.filter(action="user.deactivated").count() == 1
    # Second run: already inactive -> no new logs.
    admin.deactivate_users(request, User.objects.filter(pk=user.pk))
    assert AuditLog.objects.filter(action="user.deactivated").count() == 1


def test_profile_patch_through_middleware_writes_audit(user):
    """Full stack: PATCH /me/ via APIClient -> middleware plants actor/ip/rid -> record() auto-fills."""
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=user)
    response = client.patch(
        "/api/v1/auth/me/",
        {"full_name": "Audited Name"},
        HTTP_X_REQUEST_ID="me-patch-42",
    )
    assert response.status_code == 200
    log = AuditLog.objects.get(action="user.profile.updated")
    assert log.actor == user
    assert log.source == Source.API
    assert log.request_id == "me-patch-42"
    assert "full_name" in log.changed_fields
