from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0002_dog_capture_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="phone_number",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="profile",
            name="facebook_url",
            field=models.URLField(blank=True),
        ),
    ]
