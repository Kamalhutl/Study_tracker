"""Shared helpers for ATS parsers."""

from apps.jobs.enums import WorkMode


def work_mode_from_text(*values: object) -> str:
    """Infer a WorkMode value from free-text location or title fields."""
    blob = " ".join(str(v or "") for v in values).lower()
    if "hybrid" in blob:
        return str(WorkMode.HYBRID)
    if "remote" in blob or "work from home" in blob or "wfh" in blob:
        return str(WorkMode.REMOTE)
    if "onsite" in blob or "on-site" in blob or "in office" in blob:
        return str(WorkMode.ONSITE)
    return ""
