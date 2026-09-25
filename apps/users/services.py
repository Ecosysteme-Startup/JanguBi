"""Utilitaires utilisateurs encore partagés (journal de sécurité, envoi d'e-mail, création
de compte pour les tests historiques).

Les parcours d'inscription, d'activation, de mot de passe et de changement d'e-mail sont
assurés par Keycloak depuis la bascule du 25/09/2026 (ADR-004) ; leur code maison est retiré.
"""

import logging
import secrets
from typing import Any

from django.db import transaction

from apps.emails.services import send_multi_format_email
from apps.users.enums import UserRole
from apps.users.models import BaseUser, SecurityAuditLog

logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------

@transaction.atomic
def user_create(
    *,
    email: str,
    password: str | None = None,
    role: str = UserRole.FIDELE,
    phone_number: str | None = None,
    is_active: bool = True,
    is_verified: bool = True,
    is_staff: bool = False,
    is_admin: bool = False,
) -> BaseUser:
    """Helper de compatibilité pour les tests legacy."""
    if phone_number is None:
        phone_number = f"+22177{secrets.randbelow(10**7):07d}"

    return BaseUser.objects.create_user(
        email=email,
        phone_number=phone_number,
        role=role,
        password=password,
        is_active=is_active,
        is_verified=is_verified,
        is_staff=is_staff,
        is_admin=is_admin,
    )


def _audit(
    user: BaseUser | None,
    event: str,
    ip: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Crée une entrée dans SecurityAuditLog. Ne lève jamais d'exception."""
    try:
        SecurityAuditLog.objects.create(
            user=user,
            event=event,
            ip_address=ip,
            metadata=metadata or {},
        )
    except Exception:
        logger.exception("Impossible de créer un SecurityAuditLog.")


def _send_email_safe(template_prefix: str, ctx: dict, to: str, path_prefix: str = "auth") -> None:
    """Envoi d'email non-bloquant : loggue l'erreur sans faire planter le service."""
    from django.conf import settings as django_settings
    full_ctx = {
        "frontend_url": getattr(django_settings, "FRONTEND_URL", "http://localhost:3000"),
        **ctx,
    }
    try:
        send_multi_format_email(
            template_prefix=template_prefix,
            template_ctxt=full_ctx,
            target_email=to,
            path_prefix=path_prefix,
        )
    except Exception:
        logger.exception(f"Échec envoi email '{template_prefix}' → {to}")
