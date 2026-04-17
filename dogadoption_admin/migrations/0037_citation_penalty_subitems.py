from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("dogadoption_admin", "0036_add_reg_no_index"),
    ]

    operations = [
        migrations.AddField(
            model_name="citation",
            name="penalty_subitems",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Tier/breakdown fee lines (code, label, amount) selected with parent penalties.",
            ),
        ),
    ]
