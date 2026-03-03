from django.db import migrations, models


DEFAULT_BARANGAYS = [
    "Ali-is", "Banaybanay", "Banga", "Boyco", "Bugay", "Cansumalig", "Dawis", "Kalamtukan",
    "Kalumboyan", "Malabugas", "Mandu-ao", "Maninihon", "Minaba", "Nangka", "Narra",
    "Pagatban", "Poblacion", "San Isidro", "San Jose", "San Miguel", "San Roque", "Suba",
    "Tabuan", "Tayawan", "Tinago", "Ubos", "Villareal", "Villasol",
]


def seed_barangays(apps, schema_editor):
    Barangay = apps.get_model("dogadoption_admin", "Barangay")
    for idx, name in enumerate(DEFAULT_BARANGAYS, start=1):
        Barangay.objects.get_or_create(
            name=name,
            defaults={
                "sort_order": idx,
                "is_active": True,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0009_delete_appointmentavailability"),
    ]

    operations = [
        migrations.CreateModel(
            name="Barangay",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveIntegerField(default=0)),
            ],
            options={
                "ordering": ["sort_order", "name"],
            },
        ),
        migrations.RunPython(seed_barangays, migrations.RunPython.noop),
    ]
