from django.db import migrations, models


def _add_phase_override_started_at_if_missing(apps, schema_editor):
    Post = apps.get_model("dogadoption_admin", "Post")
    table_name = Post._meta.db_table
    column_name = "phase_override_started_at"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
    if column_name in columns:
        return

    field = models.DateTimeField(blank=True, null=True)
    field.set_attributes_from_name(column_name)
    schema_editor.add_field(Post, field)


def _remove_phase_override_started_at_if_present(apps, schema_editor):
    Post = apps.get_model("dogadoption_admin", "Post")
    table_name = Post._meta.db_table
    column_name = "phase_override_started_at"
    with schema_editor.connection.cursor() as cursor:
        columns = {
            column.name
            for column in schema_editor.connection.introspection.get_table_description(cursor, table_name)
        }
    if column_name not in columns:
        return

    field = models.DateTimeField(blank=True, null=True)
    field.set_attributes_from_name(column_name)
    schema_editor.remove_field(Post, field)


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0032_post_archive_phase_override_and_view_count"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    _add_phase_override_started_at_if_missing,
                    _remove_phase_override_started_at_if_present,
                )
            ],
            state_operations=[
                migrations.AddField(
                    model_name="post",
                    name="phase_override_started_at",
                    field=models.DateTimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
