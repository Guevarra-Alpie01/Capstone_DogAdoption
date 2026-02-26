from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0002_alter_post_rescued_date_optional"),
    ]

    operations = [
        migrations.AddField(
            model_name="citation",
            name="penalties",
            field=models.ManyToManyField(blank=True, related_name="citations", to="dogadoption_admin.penalty"),
        ),
    ]
