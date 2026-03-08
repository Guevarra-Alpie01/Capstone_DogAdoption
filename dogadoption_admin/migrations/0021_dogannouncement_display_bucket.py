from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0020_announcementreaction"),
    ]

    operations = [
        migrations.AddField(
            model_name="dogannouncement",
            name="display_bucket",
            field=models.CharField(
                choices=[
                    ("ordinary", "Ordinary"),
                    ("pinned", "Pinned"),
                    ("campaign", "Education"),
                ],
                default="ordinary",
                max_length=16,
            ),
        ),
        migrations.AddIndex(
            model_name="dogannouncement",
            index=models.Index(
                fields=["display_bucket", "created_at"],
                name="dogann_bucket_created_idx",
            ),
        ),
    ]
