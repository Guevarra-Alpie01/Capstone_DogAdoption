from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0012_certificatesettings_vaccination_defaults"),
    ]

    operations = [
        migrations.AddField(
            model_name="dogannouncement",
            name="category",
            field=models.CharField(
                choices=[
                    ("DOG_ANNOUNCEMENT", "Dog Announcements"),
                    ("DOG_LAW", "Dog Laws"),
                ],
                default="DOG_ANNOUNCEMENT",
                max_length=40,
            ),
        ),
    ]
