import nh3
from django.db import migrations
from django.db.models import Q

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "u",
        "ul",
        "ol",
        "li",
        "h3",
        "h4",
        "a",
        "code",
        "pre",
        "blockquote",
    }
)

# Create a single Cleaner instance for the migration
_SANITIZE_CLEANER = nh3.Cleaner(
    tags=_ALLOWED_TAGS,
    attributes={
        "*": set(),  # No attributes on any tag by default
        "a": {"href", "title", "target"},  # Only these attributes on <a>
    },
    link_rel="nofollow noopener noreferrer",
    url_schemes={"http", "https", "mailto"},
    set_tag_attribute_values={"a": {"target": "_blank"}},
    strip_comments=True,
)


def sanitize_html(html):
    if not html:
        return ""
    return _SANITIZE_CLEANER.clean(html)


def backfill_sanitized(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    batch_size = 500
    total = Job.objects.filter(Q(description_html_sanitized="") & ~Q(description_html="")).count()
    if total == 0:
        return
    for start in range(0, total, batch_size):
        batch = list(
            Job.objects.filter(Q(description_html_sanitized="") & ~Q(description_html="")).order_by(
                "pk"
            )[start : start + batch_size]
        )
        for job in batch:
            job.description_html_sanitized = sanitize_html(job.description_html)
        Job.objects.bulk_update(batch, ["description_html_sanitized"], batch_size=batch_size)


def reverse_backfill(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    Job.objects.all().update(description_html_sanitized="")


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0002_rename_comment_jobreport_detail_remove_savedjob_note_and_more"),
    ]
    operations = [
        migrations.RunPython(backfill_sanitized, reverse_backfill),
    ]
