from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="dogcapturerequest",
            name="notification_scheduled_for",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dogcapturerequest",
            name="notification_sent_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
