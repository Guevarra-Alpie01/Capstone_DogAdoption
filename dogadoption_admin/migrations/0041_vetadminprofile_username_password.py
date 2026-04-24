# Generated manually for vet admin staff table enhancements.

from django.db import migrations, models


def _sync_vetadmin_auth_from_user(apps, schema_editor):
    StaffAccess = apps.get_model("dogadoption_admin", "StaffAccess")
    User = apps.get_model("auth", "User")
    for row in StaffAccess.objects.all().only("id", "user_id", "username", "password"):
        u = User.objects.get(pk=row.user_id)
        # Copy stored hash and username; matches auth_user for Django login.
        row.username = u.username
        row.password = u.password
        row.save(update_fields=["username", "password"])


def _nop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0040_alter_adminnotification_table_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="staffaccess",
            name="username",
            field=models.CharField(
                help_text="Login name (kept in sync with auth user).",
                max_length=150,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name="staffaccess",
            name="password",
            field=models.CharField(
                help_text="Hashed password (kept in sync with auth user).",
                max_length=128,
                null=True,
            ),
        ),
        migrations.RunPython(_sync_vetadmin_auth_from_user, _nop_reverse),
        migrations.AlterField(
            model_name="staffaccess",
            name="password",
            field=models.CharField(
                help_text="Hashed password (kept in sync with auth user).",
                max_length=128,
            ),
        ),
        migrations.AlterField(
            model_name="staffaccess",
            name="username",
            field=models.CharField(
                help_text="Login name (kept in sync with auth user).",
                max_length=150,
                unique=True,
            ),
        ),
        migrations.RenameModel(
            old_name="StaffAccess",
            new_name="VetAdminProfile",
        ),
        migrations.AlterModelTable(
            name="vetadminprofile",
            table="dogadoption_admin_staffaccess",
        ),
    ]
