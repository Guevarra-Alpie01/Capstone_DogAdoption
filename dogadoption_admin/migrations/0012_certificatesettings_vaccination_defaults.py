from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0011_vaccinationrecord_manufacturer_lot_no"),
    ]

    operations = [
        migrations.AddField(
            model_name="certificatesettings",
            name="default_manufacturer_lot_no",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="certificatesettings",
            name="default_vac_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="certificatesettings",
            name="default_vaccine_expiry_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="certificatesettings",
            name="default_vaccine_name",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
