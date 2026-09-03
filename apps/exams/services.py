from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.exams.models import ChangeDetectedBy, ExamCycle, ExamDateChange


def compute_effective_max_age(
    eligibility: dict[str, Any],
    category: str,
    is_pwbd: bool = False,
    is_ex_serviceman: bool = False,
    service_years: int = 0,
) -> int | None:
    """
    Pure function: compute effective max age given eligibility dict and candidate attributes.
    Returns None if no max_age set.
    """
    max_age = eligibility.get("max_age")
    if max_age is None:
        return None
    relaxation = eligibility.get("age_relaxation", {})
    extra = 0
    if category in ("SC", "ST"):
        extra = relaxation.get("SC/ST", 0)
    elif category == "OBC":
        extra = relaxation.get("OBC", 0)
    if is_pwbd:
        if category in ("SC", "ST"):
            extra = max(extra, relaxation.get("PwBD_SC/ST", 0))
        elif category == "OBC":
            extra = max(extra, relaxation.get("PwBD_OBC", 0))
        else:
            extra = max(extra, relaxation.get("PwBD_General", 0))
    if is_ex_serviceman:
        # Deduct service rendered, but not below 0
        ex_service = relaxation.get("Ex-servicemen", 0)
        effective = max(0, ex_service - service_years) if service_years is not None else ex_service
        extra = max(extra, effective)
    return max_age + extra


def update_exam_cycle(
    cycle: ExamCycle,
    changes: dict[str, Any],
    source_url: str = "",
    detected_by: str = ChangeDetectedBy.SCRAPE,
    note: str = "",
    actor=None,
) -> ExamCycle:
    """
    Update cycle fields and record ExamDateChange for each changed date field.
    Also enforce publication rule: if changing verified_by_human to False, must unpublish.
    """
    date_fields = {
        "notification_date",
        "application_start",
        "application_end",
        "fee_last_date",
        "correction_window_start",
        "correction_window_end",
        "result_date",
    }
    with transaction.atomic():
        # Enforce publication rule: can't set is_published=True if not verified
        if changes.get("is_published") is True and not changes.get(
            "verified_by_human", cycle.verified_by_human
        ):
            raise ValidationError("Cannot publish a cycle that is not verified by human.")
        # Also if changing verified_by_human to False while is_published is True, unpublish
        if changes.get("verified_by_human") is False and cycle.is_published:
            changes["is_published"] = False

        for field, new_value in changes.items():
            old_value = getattr(cycle, field)
            if old_value != new_value:
                setattr(cycle, field, new_value)
                if field in date_fields:
                    ExamDateChange.objects.create(
                        cycle=cycle,
                        field_name=field,
                        old_value=str(old_value) if old_value is not None else "",
                        new_value=str(new_value) if new_value is not None else "",
                        source_url=source_url,
                        detected_by=detected_by,
                        note=note,
                    )
        cycle.save()
        # TODO: audit log entry
        return cycle
