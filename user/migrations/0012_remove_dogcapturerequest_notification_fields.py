from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("user", "0011_dogcapturerequest_preferred_appointment_date_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="dogcapturerequest",
            name="notification_scheduled_for",
        ),
        migrations.RemoveField(
            model_name="dogcapturerequest",
            name="notification_sent_at",
        ),
    ]
