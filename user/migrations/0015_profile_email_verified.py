from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0014_dogcapturerequest_hotspot_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="email_verified",
            field=models.BooleanField(default=True),
        ),
    ]
