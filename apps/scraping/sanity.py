from django.conf import settings
from django.db import models


class RunVerdict(models.TextChoices):
    TRUSTED = "trusted", "Trusted"
    QUARANTINED = "quarantined", "Quarantined"
    UNTRUSTED = "untrusted", "Untrusted"


def evaluate_run(*, run_status: str, jobs_found: int, last_jobs_seen: int) -> tuple[str, str]:
    """
    Evaluate the trustworthiness of a scrape run based on its outcome and history.

    Returns (verdict, reason) where verdict is one of RunVerdict values.
    Rules evaluated in order:
      1. run_status != 'success' -> UNTRUSTED
      2. last_jobs_seen < SCRAPE_SANITY_MIN_BASELINE -> TRUSTED
      3. jobs_found == 0 and last_jobs_seen > 0 -> QUARANTINED
      4. jobs_found < last_jobs_seen * SCRAPE_SANITY_DROP_RATIO -> QUARANTINED
      5. otherwise -> TRUSTED
    """
    if run_status != "success":
        return (RunVerdict.UNTRUSTED, f"Run status is {run_status}")

    min_baseline = getattr(settings, "SCRAPE_SANITY_MIN_BASELINE", 5)
    if last_jobs_seen < min_baseline:
        return (RunVerdict.TRUSTED, f"Below baseline ({last_jobs_seen} < {min_baseline})")

    if jobs_found == 0 and last_jobs_seen > 0:
        return (RunVerdict.QUARANTINED, f"Found 0 jobs (last had {last_jobs_seen})")

    drop_ratio = getattr(settings, "SCRAPE_SANITY_DROP_RATIO", 0.5)
    if jobs_found < last_jobs_seen * drop_ratio:
        return (
            RunVerdict.QUARANTINED,
            f"Drop ratio {jobs_found}/{last_jobs_seen} < {drop_ratio}",
        )

    return (RunVerdict.TRUSTED, "Within acceptable range")
