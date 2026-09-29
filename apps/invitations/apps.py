from django.apps import AppConfig


class InvitationsConfig(AppConfig):
    name = "apps.invitations"
    label = "invitations"
    verbose_name = "Invitations et validation des comptes du clergé"
    default_auto_field = "django.db.models.BigAutoField"
