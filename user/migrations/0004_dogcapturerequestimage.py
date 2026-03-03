from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("user", "0003_profile_contact_info"),
    ]

    operations = [
        migrations.CreateModel(
            name="DogCaptureRequestImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="dog_requests/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="user.dogcapturerequest",
                    ),
                ),
            ],
        ),
    ]
