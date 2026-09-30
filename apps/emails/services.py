import datetime
import random
from email.headerregistry import Address
from email.utils import parseaddr
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.db.models.query import QuerySet
from django.utils import timezone

from apps.common.services import model_update
from apps.core.exceptions import ApplicationError
from apps.emails.models import Email
from apps.emails.rendering import email_render
from apps.emails.tasks import email_send as email_send_task


def _from_address() -> str:
    """« Jàngu Bi <noreply@…> » : le nom s'affiche dans la boîte de réception."""
    address = settings.EMAIL_FROM_ADDRESS
    name, addr = parseaddr(address)
    display = getattr(settings, "EMAIL_FROM_NAME", "")
    if name or not display or not addr:
        return address
    return str(Address(display_name=display, addr_spec=addr))


@transaction.atomic
def email_failed(email: Email) -> Email:
    if email.status != Email.Status.SENDING:
        raise ApplicationError(f"Cannot fail non-sending emails. Current status is {email.status}")

    email, _ = model_update(instance=email, fields=["status"], data={"status": Email.Status.FAILED})
    return email


@transaction.atomic
def email_send(email: Email) -> Email:
    if email.status != Email.Status.SENDING:
        raise ApplicationError(f"Cannot send non-ready emails. Current status is {email.status}")

    if settings.EMAIL_SENDING_FAILURE_TRIGGER:
        failure_dice = random.uniform(0, 1)

        if failure_dice <= settings.EMAIL_SENDING_FAILURE_RATE:
            raise ApplicationError("Email sending failure triggered.")

    subject = email.subject
    from_email = _from_address()
    to = email.to

    html = email.html
    plain_text = email.plain_text

    msg = EmailMultiAlternatives(subject, plain_text, from_email, [to])
    msg.attach_alternative(html, "text/html")

    msg.send()

    email, _ = model_update(
        instance=email, fields=["status", "sent_at"], data={"status": Email.Status.SENT, "sent_at": timezone.now()}
    )
    return email


def email_send_all(emails: QuerySet[Email]):
    """
    This is a very specific service.

    We don't want to decorate with @transaction.atomic,
    since we are executing updates, 1 by 1, in a separate atomic block,
    so we can trigger transaction.on_commit for each email, separately.
    """
    for email in emails:
        with transaction.atomic():
            Email.objects.filter(id=email.id).update(status=Email.Status.SENDING)

        # Create a closure, to capture the proper value of each id
        transaction.on_commit((lambda email_id: lambda: email_send_task.delay(email_id))(email.id))


@transaction.atomic
def email_queue(
    *,
    to: str,
    template: str,
    context: dict[str, Any] | None = None,
    eta: datetime.datetime | None = None,
) -> Email:
    """Rend l'e-mail ``template`` (gabarit de base Jàngu Bi, HTML + texte), l'enregistre et
    programme son envoi après commit (tout de suite, ou à ``eta``). Jamais de SMTP direct."""
    rendered = email_render(template=template, context=context)
    email = Email.objects.create(
        to=to,
        subject=rendered.subject,
        html=rendered.html,
        plain_text=rendered.plain_text,
        status=Email.Status.SENDING,
    )
    if eta is None:
        transaction.on_commit(lambda: email_send_task.delay(email.id))
    else:
        transaction.on_commit(lambda: email_send_task.apply_async(args=[email.id], eta=eta))
    return email


@transaction.atomic
def email_queue_many(*, recipients: list[str], template: str, context: dict[str, Any] | None = None) -> list[Email]:
    """Même e-mail à plusieurs personnes (un envoi chacune) : rendu une seule fois."""
    rendered = email_render(template=template, context=context)
    emails = Email.objects.bulk_create(
        [
            Email(
                to=to,
                subject=rendered.subject,
                html=rendered.html,
                plain_text=rendered.plain_text,
                status=Email.Status.SENDING,
            )
            for to in recipients
            if to
        ]
    )
    for email in emails:
        transaction.on_commit((lambda email_id: lambda: email_send_task.delay(email_id))(email.id))
    return emails


@transaction.atomic
def send_multi_format_email(
    *,
    template_prefix: str,
    template_ctxt: dict,
    target_email: str,
    path_prefix: str = "auth",
) -> None:
    """Rend ``<path_prefix>/<template_prefix>`` (objet, HTML, texte), enregistre l'Email et l'envoie via Celery."""
    email_queue(to=target_email, template=f"{path_prefix}/{template_prefix}", context=template_ctxt)
