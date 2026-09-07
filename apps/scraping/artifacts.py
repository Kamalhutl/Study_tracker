import gzip
import logging

from apps.companies.models import Company
from apps.scraping.models import ScrapeArtifact, ScrapeRun

logger = logging.getLogger("study_tracker.scraping.artifacts")

# Cap for stored artifact size (512 KiB)
ARTIFACT_MAX_BYTES = 512 * 1024


def store_artifact(
    *,
    scrape_run: ScrapeRun,
    company: Company,
    url: str,
    body: str,
) -> None:
    """Store a compressed artifact for a failed/quarantined run.

    This function is failure-isolated: any exception is logged and swallowed.
    """
    try:
        if not body:
            return

        # Encode and compress
        body_bytes = body.encode("utf-8")
        original_size = len(body_bytes)

        # Cap if too large
        truncated = False
        if original_size > ARTIFACT_MAX_BYTES:
            body_bytes = body_bytes[:ARTIFACT_MAX_BYTES]
            truncated = True

        compressed = gzip.compress(body_bytes, compresslevel=6)

        ScrapeArtifact.objects.create(
            scrape_run=scrape_run,
            company=company,
            url=url,
            content_gzip=compressed,
            content_type="text/html; charset=utf-8",  # Simplification; could be derived
            byte_size=original_size,
            truncated=truncated,
        )
    except Exception as e:
        logger.error("Failed to store artifact for run %s: %s", scrape_run.id, e, exc_info=True)


def read_artifact(artifact: ScrapeArtifact) -> str:
    """Decompress and return the artifact content as a string."""
    try:
        decompressed = gzip.decompress(artifact.content_gzip)
        return decompressed.decode("utf-8")
    except Exception as e:
        logger.error("Failed to read artifact %s: %s", artifact.id, e, exc_info=True)
        raise
