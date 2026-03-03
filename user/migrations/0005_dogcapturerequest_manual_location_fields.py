from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0004_dogcapturerequestimage"),
    ]

    operations = [
        migrations.AddField(
            model_name="dogcapturerequest",
            name="manual_full_address",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dogcapturerequest",
            name="location_landmark_image",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="dog_request_landmarks/",
            ),
        ),
    ]
