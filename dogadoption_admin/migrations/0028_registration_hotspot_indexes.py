from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0027_delete_dogcatchercontact"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="dog",
            index=models.Index(
                fields=["owner_user", "date_registered"],
                name="dog_owneruser_date_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="dog",
            index=models.Index(
                fields=["owner_name_key", "date_registered"],
                name="dog_ownerkey_date_idx",
            ),
        ),
    ]
