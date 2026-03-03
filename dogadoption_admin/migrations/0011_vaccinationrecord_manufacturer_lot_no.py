from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0010_barangay"),
    ]

    operations = [
        migrations.AddField(
            model_name="vaccinationrecord",
            name="manufacturer_lot_no",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
