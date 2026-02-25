from django.apps import AppConfig

class DogadoptionAdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'dogadoption_admin'

    def ready(self):
        import dogadoption_admin.signals