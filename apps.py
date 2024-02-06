from django.apps import AppConfig


class VoteitToolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "voteit_tools"

    def ready(self):
        from .exportimport.rest_api import views
