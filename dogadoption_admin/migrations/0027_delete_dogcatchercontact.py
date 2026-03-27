from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0026_staffaccess"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DogCatcherContact",
        ),
    ]
