"""Formulaire public « Pour les paroisses » (SRS §7, contact paroisses).

Aucune donnée de la demande n'est écrite dans les journaux : elle est enregistrée puis
transmise par e-mail à Numerisen (modèle ``Email`` + tâche, jamais de SMTP direct).
"""

from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.contact.models import PresentationRequest
from apps.contact.selectors import diocese_get_or_none
from apps.core.exceptions import ApplicationError
from apps.emails.services import send_multi_format_email


class ContactValidationError(ApplicationError):
    """Erreur rattachée à un champ du formulaire (``extra["field"]``)."""

    code = "validation_error"


@transaction.atomic
def presentation_request_create(
    *,
    full_name: str,
    fonction: str,
    paroisse: str,
    diocese_node_id: UUID | None,
    telephone: str,
    email: str,
    message: str = "",
    consentement: bool,
    cure_informe: bool,
) -> PresentationRequest:
    if consentement is not True:
        raise ContactValidationError("Le consentement est obligatoire.", {"field": "consentement"})
    diocese = None
    if diocese_node_id is not None:
        diocese = diocese_get_or_none(node_id=diocese_node_id)
        if diocese is None:
            raise ContactValidationError("Diocèse introuvable.", {"field": "diocese_node_id"})

    request = PresentationRequest.objects.create(
        full_name=full_name,
        fonction=fonction,
        paroisse=paroisse,
        diocese_node=diocese,
        telephone=telephone,
        email=email,
        message=message,
        consented_at=timezone.now(),
        cure_informe=cure_informe,
    )
    send_multi_format_email(
        template_prefix="presentation_request",
        template_ctxt={"request": request},
        target_email=settings.CONTACT_EMAIL,
        path_prefix="contact",
    )
    return request
