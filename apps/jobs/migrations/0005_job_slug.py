from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("jobs", "0004_remove_job_idx_job_search_vector_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="job",
            name="slug",
            field=models.SlugField(
                max_length=320, unique=True, db_index=True, blank=True, null=True
            ),
        ),
    ]
