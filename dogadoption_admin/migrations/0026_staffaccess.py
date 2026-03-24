from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0025_post_gender"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffAccess",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("can_create_posts", models.BooleanField(default=False)),
                ("can_view_post_history", models.BooleanField(default=False)),
                ("can_view_status_cards", models.BooleanField(default=False)),
                ("can_manage_capture_requests", models.BooleanField(default=False)),
                ("can_access_registration", models.BooleanField(default=False)),
                ("can_access_registration_list", models.BooleanField(default=False)),
                ("can_access_vaccination", models.BooleanField(default=False)),
                ("can_access_vaccination_list", models.BooleanField(default=False)),
                ("can_access_citations", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="staff_access", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "verbose_name": "Staff access",
                "verbose_name_plural": "Staff access",
            },
        ),
    ]
