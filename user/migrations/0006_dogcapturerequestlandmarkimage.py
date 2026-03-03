from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0005_dogcapturerequest_manual_location_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DogCaptureRequestLandmarkImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="dog_request_landmarks/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="landmark_images",
                        to="user.dogcapturerequest",
                    ),
                ),
            ],
        ),
    ]
