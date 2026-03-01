from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("dogadoption_admin", "0008_globalappointmentdate"),
    ]

    operations = [
        migrations.DeleteModel(
            name="AppointmentAvailability",
        ),
    ]
