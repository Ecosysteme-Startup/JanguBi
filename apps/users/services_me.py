"""Profil de la personne connectée (SRS EF-PER-01)."""

from typing import Any

from django.db import transaction

from apps.core.exceptions import ApplicationError
from apps.users.models import Profile

PROFILE_FIELDS = ("first_name", "last_name", "title", "date_of_birth", "phone")


@transaction.atomic
def me_profile_update(*, user: Any, data: dict[str, Any]) -> Any:
    """Seuls les champs du profil sont modifiables ici. L'e-mail et le mot de passe se gèrent
    dans Keycloak ; l'état de vie passe par la déclaration vérifiée (/me/declaration/)."""
    unknown = set(data) - set(PROFILE_FIELDS)
    if unknown:
        raise ApplicationError("Champs non modifiables.", {"fields": sorted(unknown)}, code="field_not_updatable")
    profile, _ = Profile.objects.get_or_create(user=user)
    for field, value in data.items():
        setattr(profile, field, value)
    profile.save(update_fields=[*data, "updated_at"])
    if {"first_name", "last_name"} & set(data):
        _keycloak_push_on_commit(user)
    user.profile = profile  # cache de la relation inverse : la réponse relit le profil à jour
    return user


def _keycloak_push_on_commit(user: Any) -> None:
    """Le nom vit aussi dans Keycloak : poussé après validation (tâche réessayée)."""
    from django.conf import settings

    if not settings.KEYCLOAK_ENABLED or not getattr(user, "keycloak_sub", None):
        return
    from apps.users.tasks import keycloak_account_push_task

    transaction.on_commit(lambda: keycloak_account_push_task.delay(str(user.pk)))
