from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0013_user_posts_optional_description_and_age"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dogcapturerequest",
            index=models.Index(
                fields=["status", "scheduled_date", "created_at"],
                name="dogcap_stat_sched_cr_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="dogcapturerequest",
            index=models.Index(
                fields=["status", "latitude", "longitude", "created_at"],
                name="dogcap_stat_coords_cr_idx",
            ),
        ),
    ]
