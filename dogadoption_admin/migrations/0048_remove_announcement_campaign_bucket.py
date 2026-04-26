from django.db import migrations, models


def forwards(apps, schema_editor):
    DogAnnouncement = apps.get_model("dogadoption_admin", "DogAnnouncement")
    DogAnnouncement.objects.filter(display_bucket="campaign").update(display_bucket="ordinary")


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0047_dog_surrender_breed_age_and_surrenderdogs_table"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
        migrations.AlterField(
            model_name="dogannouncement",
            name="display_bucket",
            field=models.CharField(
                choices=[("ordinary", "Ordinary"), ("pinned", "Pinned")],
                default="ordinary",
                max_length=16,
            ),
        ),
    ]
