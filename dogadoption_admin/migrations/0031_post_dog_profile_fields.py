from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0030_delete_userviolationrecord"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="age_group",
            field=models.CharField(
                blank=True,
                choices=[
                    ("puppy", "Puppy (< 1 year)"),
                    ("young", "Young (1-3 years)"),
                    ("adult", "Adult (3-8 years)"),
                    ("senior", "Senior (8+ years)"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="breed",
            field=models.CharField(
                blank=True,
                choices=[
                    ("aspin", "Aspin / Mixed Local Breed"),
                    ("beagle", "Beagle"),
                    ("chihuahua", "Chihuahua"),
                    ("dachshund", "Dachshund"),
                    ("french_bulldog", "French Bulldog"),
                    ("german_shepherd", "German Shepherd"),
                    ("golden_retriever", "Golden Retriever"),
                    ("husky", "Siberian Husky"),
                    ("labrador", "Labrador Retriever"),
                    ("pomeranian", "Pomeranian"),
                    ("poodle", "Poodle"),
                    ("rottweiler", "Rottweiler"),
                    ("shih_tzu", "Shih Tzu"),
                    ("other", "Other"),
                ],
                default="",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="breed_other",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="post",
            name="coat_length",
            field=models.CharField(
                blank=True,
                choices=[
                    ("short", "Short"),
                    ("medium", "Medium"),
                    ("long", "Long"),
                    ("wire", "Wire"),
                    ("hairless", "Hairless"),
                    ("curly", "Curly"),
                ],
                default="",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="post",
            name="color_other",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="post",
            name="colors",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="post",
            name="size_group",
            field=models.CharField(
                blank=True,
                choices=[
                    ("small", "Small (up to 25 lbs)"),
                    ("medium", "Medium (26-60 lbs)"),
                    ("large", "Large (61-100 lbs)"),
                    ("x_large", "X-Large (> 100 lbs)"),
                ],
                default="",
                max_length=20,
            ),
        ),
    ]
