"""Tâches de synchronisation Keycloak (docs/ADMIN-KEYCLOAK.md). Import des services dans le corps."""

from celery import shared_task

from apps.authentication.keycloak_admin import KeycloakAdminError


@shared_task(bind=True, max_retries=8, default_retry_delay=30)
def keycloak_event_process_task(self, event_id: int) -> str:
    """Événement du SPI Keycloak : relecture du compte concerné et alignement de l'application."""
    from apps.users.services_keycloak_sync import keycloak_event_process

    try:
        return keycloak_event_process(event_id=event_id)
    except KeycloakAdminError as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=8, default_retry_delay=30)
def keycloak_account_push_task(self, user_id: str) -> str:
    """Pousse vers Keycloak un changement d'identité fait dans l'application (profil)."""
    from apps.users.models import BaseUser
    from apps.users.services_keycloak_sync import account_push

    user = BaseUser.objects.filter(pk=user_id).first()
    if user is None:
        return "ignore"
    try:
        return account_push(user=user)
    except KeycloakAdminError as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, max_retries=8, default_retry_delay=60)
def keycloak_actions_email_task(self, keycloak_id: str, actions: list[str]) -> str:
    """E-mail d'actions requises envoyé par Keycloak (invitation, mot de passe, vérification)."""
    from apps.users.services_admin import keycloak_actions_email_send

    try:
        keycloak_actions_email_send(keycloak_id=keycloak_id, actions=actions)
    except KeycloakAdminError as exc:
        raise self.retry(exc=exc) from exc
    return "envoye"


@shared_task
def keycloak_events_poll_task() -> dict[str, int]:
    """Chaque minute : événements Keycloak lus par l'Admin REST API (curseur), comptes alignés."""
    from apps.users.services_keycloak_sync import keycloak_events_poll

    return keycloak_events_poll()


@shared_task
def keycloak_accounts_reconcile_task() -> dict[str, int]:
    """Réconciliation périodique : écarts détectés et corrigés, rapport archivé."""
    from django.conf import settings

    from apps.users.services_keycloak_sync import keycloak_reconcile

    if not settings.KEYCLOAK_ENABLED:
        return {}
    return keycloak_reconcile(dry_run=False, trigger="tache").counts
