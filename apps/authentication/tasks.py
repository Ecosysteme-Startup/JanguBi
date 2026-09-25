import httpx
from celery import shared_task

from apps.authentication.keycloak_admin import KeycloakAdminError


@shared_task(bind=True, max_retries=5, default_retry_delay=20)
def keycloak_staff_sync_task(self, person_id: str) -> str:
    """Rôle ``staff`` après une nomination, une fin ou une annulation (EF-AUTH-04 : < 1 min)."""
    from django.contrib.auth import get_user_model

    from apps.authentication.services_keycloak import keycloak_staff_role_sync  # import local (HackSoft)

    person = get_user_model().objects.filter(pk=person_id).first()
    if person is None:
        return "skipped"
    try:
        return keycloak_staff_role_sync(person=person)
    except (httpx.HTTPError, KeycloakAdminError) as exc:
        raise self.retry(exc=exc) from exc


@shared_task
def keycloak_staff_reconcile_task() -> dict[str, int]:
    from apps.authentication.services_keycloak import keycloak_staff_reconcile

    return keycloak_staff_reconcile()
