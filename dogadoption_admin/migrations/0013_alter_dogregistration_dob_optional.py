from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0012_certificatesettings_vaccination_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dogregistration",
            name="dob",
            field=models.DateField(blank=True, null=True),
        ),
    ]
