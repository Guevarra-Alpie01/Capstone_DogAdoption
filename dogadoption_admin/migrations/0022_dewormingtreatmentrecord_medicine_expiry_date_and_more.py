from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0021_dogannouncement_display_bucket"),
    ]

    operations = [
        migrations.AddField(
            model_name="dewormingtreatmentrecord",
            name="medicine_expiry_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="adminnotification",
            name="event_key",
            field=models.CharField(blank=True, db_index=True, default="", max_length=255),
        ),
    ]
