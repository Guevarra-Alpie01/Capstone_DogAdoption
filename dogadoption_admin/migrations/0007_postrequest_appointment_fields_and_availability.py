from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("dogadoption_admin", "0006_alter_dogregistration_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="postrequest",
            name="appointment_date",
            field=models.DateField(
                blank=True,
                help_text="Preferred date selected by the user.",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="postrequest",
            name="scheduled_appointment_date",
            field=models.DateField(
                blank=True,
                help_text="Final appointment date assigned by admin.",
                null=True,
            ),
        ),
        migrations.CreateModel(
            name="AppointmentAvailability",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "request_type",
                    models.CharField(choices=[("claim", "Claim"), ("adopt", "Adopt")], max_length=10),
                ),
                ("appointment_date", models.DateField()),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_appointment_dates",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "post",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="appointment_availability",
                        to="dogadoption_admin.post",
                    ),
                ),
            ],
            options={
                "ordering": ["appointment_date"],
                "unique_together": {("post", "request_type", "appointment_date")},
            },
        ),
    ]
