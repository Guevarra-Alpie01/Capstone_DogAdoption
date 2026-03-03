from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="rescued_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
