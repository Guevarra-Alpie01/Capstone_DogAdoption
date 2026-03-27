from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0012_remove_dogcapturerequest_notification_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="missingdogpost",
            name="age",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="missingdogpost",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="useradoptionpost",
            name="age",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="useradoptionpost",
            name="description",
            field=models.TextField(blank=True),
        ),
    ]
