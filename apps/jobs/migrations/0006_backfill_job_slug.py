from django.db import migrations
from django.utils.text import slugify


def backfill_slugs(apps, schema_editor):
    Job = apps.get_model("jobs", "Job")
    batch_size = 500
    total = Job.objects.filter(slug__isnull=True).count()
    if total == 0:
        return
    for start in range(0, total, batch_size):
        batch = list(
            Job.objects.filter(slug__isnull=True)
            .select_related("company")
            .order_by("pk")[start : start + batch_size]
        )
        for job in batch:
            base = slugify(f"{job.title}-{job.company.name}-{job.city}")[:311]
            suffix = str(job.id)[:8]
            job.slug = f"{base}-{suffix}"
        Job.objects.bulk_update(batch, ["slug"], batch_size=batch_size)


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0005_job_slug"),
    ]

    operations = [
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
    ]
