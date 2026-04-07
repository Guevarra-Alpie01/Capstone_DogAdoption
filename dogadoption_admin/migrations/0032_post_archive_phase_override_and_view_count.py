from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0031_post_dog_profile_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="is_history",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="post",
            name="phase_override",
            field=models.CharField(
                blank=True,
                choices=[("claim", "Redeem"), ("adopt", "Adoption")],
                default="",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="view_count",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="post",
            index=models.Index(
                fields=["is_history", "status", "created_at"],
                name="post_hist_status_created_idx",
            ),
        ),
    ]
