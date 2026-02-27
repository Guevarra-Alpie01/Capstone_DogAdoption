from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0005_admin_notification"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dogregistration",
            name="status",
            field=models.CharField(
                choices=[
                    ("None", "None"),
                    ("Castrated", "Castrated"),
                    ("Spayed", "Spayed"),
                    ("Intact", "Intact"),
                ],
                max_length=20,
            ),
        ),
    ]
