from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0013_dogannouncement_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="DogAnnouncementImage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("image", models.ImageField(upload_to="announcements/photos/")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "announcement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="dogadoption_admin.dogannouncement",
                    ),
                ),
            ],
            options={"ordering": ["created_at", "id"]},
        ),
    ]
