"""Dons et quêtes : toutes les écritures (ADR-017 ; cadrage DONS-00).

Principes :
- un don est rattaché à un fonds et n'en change jamais (c. 1267 §3) ;
- un don en ligne n'est confirmé que par le serveur (notification signée contre-vérifiée, ou
  réconciliation), jamais par le retour du navigateur ;
- aucun montant, nom ni e-mail dans les logs (loi 2008-12) : on ne journalise que des références.
"""

import datetime
import hashlib
import logging
import math
import secrets
import uuid
from functools import partial
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.exceptions import ApplicationError, ConflictError, PermissionDeniedError
from apps.donations import access
from apps.donations.enums import (
    DONATION_TRANSITIONS,
    PARISH_TYPES,
    AdjustmentKind,
    AttemptStatus,
    CashCollectionStatus,
    DonationChannel,
    DonationSource,
    DonationStatus,
    FundDestination,
    FundKind,
    FundStatus,
    IncidentKind,
    PaymentMethod,
    PayoutStatus,
    StatusSource,
    WebhookStatus,
)
from apps.donations.models import (
    CashCollection,
    Donation,
    DonationActivation,
    DonationAdjustment,
    DonationStatusChange,
    Fund,
    FundUpdate,
    MonthClosing,
    PaymentAttempt,
    PaymentIncident,
    PaymentWebhookEvent,
    Payout,
    PayoutLine,
    ReceiptSequence,
)
from apps.donations.providers import get_provider
from apps.donations.providers.base import (
    CheckoutRequest,
    InvalidSignature,
    PaymentState,
    PayoutData,
    ProviderError,
    ProviderStatus,
)
from apps.hierarchy import authz
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.audit import audit_log
from apps.hierarchy.models import Node, PlaceOfWorship

logger = logging.getLogger(__name__)

EDITABLE_FUND_FIELDS = (
    "title",
    "description",
    "starts_on",
    "ends_on",
    "goal_amount",
    "authorization_ref",
    "image",
    "place",
)
MAX_CASH_AMOUNT = 50_000_000
IMPEREE_REMIT_DAYS = 7


class ProviderUnavailable(ApplicationError):
    status_code = 503
    code = "provider_unavailable"


# --- Montants -------------------------------------------------------------------------------


def fees_compute(*, amount: int, fees_covered: bool) -> tuple[int, int, int]:
    """(frais, montant payé, montant affecté au fonds). H3 : frais estimés, arrondis au franc supérieur."""
    fee = math.ceil(amount * settings.DONATIONS_FEE_RATE_BP / 10_000)
    if fees_covered:
        return fee, amount + fee, amount
    return fee, amount, max(amount - fee, 0)


def _check_amount(amount: Any) -> int:
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ApplicationError("Le montant doit être un nombre entier de francs CFA.", code="invalid_amount")
    if not settings.DONATIONS_MIN_AMOUNT <= amount <= settings.DONATIONS_MAX_AMOUNT:
        raise ApplicationError(
            "Le montant est hors des limites acceptées.",
            {"min": settings.DONATIONS_MIN_AMOUNT, "max": settings.DONATIONS_MAX_AMOUNT},
            code="amount_out_of_range",
        )
    return amount


def _new_reference() -> str:
    """Référence lisible au téléphone, qui ne révèle rien : « 4817-2093-6651 »."""
    digits = str(secrets.randbelow(9 * 10**11) + 10**11)
    return f"{digits[:4]}-{digits[4:8]}-{digits[8:]}"


def _receipt_prefix(node: Node) -> str:
    activation = DonationActivation.objects.filter(node=node).only("receipt_prefix").first()
    if activation and activation.receipt_prefix:
        return activation.receipt_prefix.upper()
    return "".join(ch for ch in node.code.upper() if ch.isalnum())[:8] or "JB"


def _receipt_number_next(*, node: Node, year: int) -> str:
    """Numéro suivant de la série de la paroisse (verrou sur le compteur : série sans trou)."""
    sequence, _ = ReceiptSequence.objects.get_or_create(node=node, year=year)
    sequence = ReceiptSequence.objects.select_for_update().get(pk=sequence.pk)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    return f"{_receipt_prefix(node)}-{year}-{sequence.last_number:05d}"


# --- Activation (H4) ------------------------------------------------------------------------


@transaction.atomic
def activation_set(
    *,
    actor: Any,
    node: Node,
    enabled: bool,
    authorization_ref: str = "",
    authorization_date: datetime.date | None = None,
    authorization_text: str = "",
    allocation_key: str = "",
    receipt_prefix: str = "",
) -> DonationActivation:
    """Ouvre ou ferme la collecte d'une paroisse. Réservé à la plateforme, sur autorisation écrite."""
    if not authz.peut(actor, "plateforme.admin", None):
        raise PermissionDeniedError("Réservé à l'administration de la plateforme.", code="dons_forbidden")
    if not access.is_parish(node):
        raise ApplicationError("La collecte s'active sur une paroisse.", code="not_a_parish")
    if enabled and not authorization_ref:
        raise ApplicationError(
            "La référence de l'autorisation écrite de l'Ordinaire est obligatoire (c. 1265).",
            code="authorization_required",
        )
    activation, _ = DonationActivation.objects.update_or_create(
        node=node,
        defaults={
            "enabled": enabled,
            "authorization_ref": authorization_ref,
            "authorization_date": authorization_date,
            "authorization_text": authorization_text,
            "allocation_key": allocation_key,
            "receipt_prefix": receipt_prefix.upper(),
        },
    )
    audit_log(actor=actor, action="dons.activation", target=activation, node=node, metadata={"enabled": enabled})
    return activation


def _activation_or_error(node: Node) -> DonationActivation:
    activation = DonationActivation.objects.filter(node=node, enabled=True).first()
    if activation is None:
        raise ApplicationError("La collecte n'est pas ouverte pour cette paroisse.", code="donations_disabled")
    return activation


# --- Fonds ----------------------------------------------------------------------------------


@transaction.atomic
def fund_create(
    *,
    actor: Any,
    node: Node,
    kind: str,
    title: str,
    description: str = "",
    starts_on: datetime.date | None = None,
    ends_on: datetime.date | None = None,
    goal_amount: int | None = None,
    authorization_ref: str = "",
    image: Any = None,
    place: PlaceOfWorship | None = None,
) -> Fund:
    access.require_parish_level(actor, "dons.gerer_fonds", node)
    if kind == FundKind.QUETE_IMPEREE:
        raise ApplicationError("Une quête impérée est définie par le diocèse.", code="imperee_from_diocese")
    if kind not in FundKind.values:
        raise ApplicationError("Type de fonds inconnu.", code="invalid_kind")
    _check_period(starts_on, ends_on)
    _check_image(image)
    _check_place(place, node)
    fund = Fund.objects.create(
        node=node,
        kind=kind,
        destination=FundDestination.PAROISSE,
        title=title,
        description=description,
        starts_on=starts_on,
        ends_on=ends_on,
        goal_amount=goal_amount if kind == FundKind.CAMPAGNE else None,
        decided_by=actor,
        decided_by_office=access.office_code_for(actor, "dons.gerer_fonds", node),
        authorization_ref=authorization_ref,
        image=image,
        place=place,
    )
    audit_log(actor=actor, action="dons.fonds_creation", target=fund, node=node, metadata={"kind": kind})
    return fund


def _check_period(starts_on: datetime.date | None, ends_on: datetime.date | None) -> None:
    if starts_on and ends_on and ends_on < starts_on:
        raise ApplicationError("La fin doit suivre le début.", code="invalid_period")


def _check_place(place: PlaceOfWorship | None, node: Node) -> None:
    if place is not None and (place.node_id != node.pk or not place.is_active):
        raise ApplicationError("Ce lieu n'appartient pas à la paroisse.", code="place_outside")


def _check_image(image: Any) -> None:
    if image is not None and not image.is_valid:
        raise ApplicationError("Le visuel n'est pas encore téléversé.", code="file_not_ready")


def _require_parish_fund(fund: Fund, actor: Any) -> None:
    access.require_parish_level(actor, "dons.gerer_fonds", fund.node)
    if fund.parent_id is not None:
        raise ApplicationError("Cette quête impérée est gérée par le diocèse.", code="imperee_from_diocese")


@transaction.atomic
def fund_update(*, fund: Fund, actor: Any, **fields: Any) -> Fund:
    _require_parish_fund(fund, actor)
    if fund.status == FundStatus.CLOS:
        raise ApplicationError("Un fonds clos ne se modifie plus.", code="fund_closed")
    unknown = set(fields) - set(EDITABLE_FUND_FIELDS)
    if unknown:
        raise ApplicationError("Champ non modifiable.", {"fields": sorted(unknown)}, code="field_not_editable")
    _check_period(fields.get("starts_on", fund.starts_on), fields.get("ends_on", fund.ends_on))
    if "image" in fields:
        _check_image(fields["image"])
    if "place" in fields:
        _check_place(fields["place"], fund.node)
    if "goal_amount" in fields and fund.kind != FundKind.CAMPAGNE:
        fields["goal_amount"] = None
    for name, value in fields.items():
        setattr(fund, name, value)
    fund.save()
    audit_log(
        actor=actor, action="dons.fonds_modification", target=fund, node=fund.node, metadata={"fields": sorted(fields)}
    )
    return fund


@transaction.atomic
def fund_publish(*, fund: Fund, actor: Any) -> Fund:
    _require_parish_fund(fund, actor)
    if fund.status != FundStatus.BROUILLON:
        raise ApplicationError("Seul un brouillon se publie.", code="invalid_transition")
    fund.status = FundStatus.OUVERT
    fund.published_at = timezone.now()
    fund.save(update_fields=["status", "published_at", "updated_at"])
    audit_log(actor=actor, action="dons.fonds_publication", target=fund, node=fund.node)
    return fund


@transaction.atomic
def fund_close(*, fund: Fund, actor: Any) -> Fund:
    access.require_parish_level(actor, "dons.gerer_fonds", fund.node)
    if fund.status != FundStatus.OUVERT:
        raise ApplicationError("Seul un fonds ouvert se clôt.", code="invalid_transition")
    fund.status = FundStatus.CLOS
    fund.closed_at = timezone.now()
    fund.save(update_fields=["status", "closed_at", "updated_at"])
    audit_log(actor=actor, action="dons.fonds_cloture", target=fund, node=fund.node)
    return fund


@transaction.atomic
def fund_news_post(*, fund: Fund, actor: Any, body: str) -> FundUpdate:
    access.require_parish_level(actor, "dons.gerer_fonds", fund.node)
    if fund.kind != FundKind.CAMPAGNE:
        raise ApplicationError("Les nouvelles concernent les campagnes.", code="not_a_campaign")
    if not body.strip():
        raise ApplicationError("La nouvelle est vide.", code="empty_body")
    update = FundUpdate.objects.create(fund=fund, author=actor, body=body.strip())
    audit_log(actor=actor, action="dons.campagne_nouvelle", target=fund, node=fund.node)
    return update


# --- Quêtes impérées (c. 1266) --------------------------------------------------------------


@transaction.atomic
def imperee_create(
    *,
    actor: Any,
    diocese: Node,
    title: str,
    description: str = "",
    starts_on: datetime.date,
    ends_on: datetime.date | None = None,
    parishes: list[Node] | None = None,
    authorization_ref: str = "",
    remit_by: datetime.date | None = None,
    messe_anticipee_incluse: bool = False,
) -> Fund:
    """Quête impérée diocésaine, déclinée en un fonds par paroisse concernée (destination : curie).

    Sans liste de paroisses : toutes les paroisses du diocèse dont la collecte est activée.
    Échéance de remise des espèces à la curie : ``remit_by``, par défaut sept jours après la quête.
    ``messe_anticipee_incluse`` : la quête de la messe anticipée de la veille au soir en fait partie
    (décision du diocèse, quête par quête)."""
    access.require_diocese(actor, "dons.definir_quete_imperee", diocese)
    _check_period(starts_on, ends_on)
    remit_by = remit_by or (ends_on or starts_on) + datetime.timedelta(days=IMPEREE_REMIT_DAYS)
    if remit_by < (ends_on or starts_on):
        raise ApplicationError("L'échéance de remise suit la quête.", code="invalid_remit_by")
    if parishes is None:
        targets = list(
            Node.objects.filter(
                path__startswith=diocese.path,
                type__code__in=PARISH_TYPES,
                donation_activation__enabled=True,
            ).select_related("type")
        )
    else:
        targets = list(parishes)
        for parish in targets:
            if not access.is_parish(parish) or not parish.path.startswith(diocese.path) or parish.pk == diocese.pk:
                raise ApplicationError(
                    "Une paroisse choisie n'appartient pas au diocèse.", {"node": str(parish.pk)}, code="parish_outside"
                )
    if not targets:
        raise ApplicationError("Aucune paroisse concernée.", code="no_parish")
    office = access.office_code_for(actor, "dons.definir_quete_imperee", diocese)
    common = {
        "kind": FundKind.QUETE_IMPEREE,
        "destination": FundDestination.CURIE,
        "title": title,
        "description": description,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "decided_by": actor,
        "decided_by_office": office,
        "authorization_ref": authorization_ref,
        "remit_by": remit_by,
        "messe_anticipee_incluse": messe_anticipee_incluse,
        "status": FundStatus.OUVERT,
        "published_at": timezone.now(),
    }
    parent = Fund.objects.create(node=diocese, **common)
    Fund.objects.bulk_create([Fund(node=parish, parent=parent, **common) for parish in targets])
    audit_log(
        actor=actor,
        action="dons.quete_imperee_creation",
        target=parent,
        node=diocese,
        metadata={"paroisses": len(targets)},
    )
    return parent


# --- Checkout (don en ligne) ----------------------------------------------------------------


def _check_fund_open(fund: Fund) -> DonationActivation:
    if not access.is_parish(fund.node):
        raise ApplicationError("On donne au fonds d'une paroisse.", code="not_a_parish_fund")
    activation = _activation_or_error(fund.node)
    today = timezone.localdate()
    if (
        fund.status != FundStatus.OUVERT
        or (fund.starts_on and today < fund.starts_on)
        or (fund.ends_on and today > fund.ends_on)
    ):
        raise ApplicationError("Ce fonds n'est pas ouvert aux dons.", code="fund_not_open")
    return activation


def checkout_create(
    *,
    fund: Fund,
    amount: Any,
    fees_covered: bool,
    anonymous: bool,
    donor: Any = None,
    donor_email: str = "",
    idempotency_key: str = "",
    source: str = DonationSource.INCONNU,
    place: PlaceOfWorship | None = None,
) -> tuple[Donation, PaymentAttempt, bool]:
    """Crée le don (``initie``) et la session de paiement chez l'agrégateur (``en_attente``).

    L'appel à l'agrégateur a lieu hors transaction ; un échec passe le don en ``echoue``.
    Une même clé d'idempotence renvoie le même don (double clic, reprise réseau) ; le booléen
    dit si le don vient d'être créé.

    ``source`` : canal d'entrée déclaré par la page de don (``?src=``) ; ``place`` : lieu de culte
    (QR code affiché dans le lieu), sinon celui du fonds."""
    amount = _check_amount(amount)
    if source not in DonationSource.values:
        source = DonationSource.INCONNU
    donor = donor if getattr(donor, "is_authenticated", False) else None
    if idempotency_key:
        existing = PaymentAttempt.objects.select_related("donation").filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            if existing.donation.fund_id != fund.pk or existing.donation.amount != amount:
                raise ConflictError(
                    "Cette clé d'idempotence a déjà servi pour un autre don.", code="idempotency_conflict"
                )
            return existing.donation, existing, False
    activation = _check_fund_open(fund)
    _check_place(place, fund.node)
    provider = get_provider()
    fee, charged, net = fees_compute(amount=amount, fees_covered=fees_covered)
    try:
        with transaction.atomic():
            donation = Donation.objects.create(
                reference=_new_reference(),
                fund=fund,
                amount=amount,
                fees_covered=fees_covered,
                fee_amount=fee,
                charged_amount=charged,
                net_amount=net,
                anonymous=anonymous,
                donor=donor,
                donor_email="" if donor else (donor_email or "").strip().lower(),
                channel=DonationChannel.EN_LIGNE,
                source=source,
                place_id=place.pk if place is not None else fund.place_id,
                status=DonationStatus.INITIE,
                status_changed_at=timezone.now(),
            )
            attempt = PaymentAttempt.objects.create(
                donation=donation, provider=provider.code, idempotency_key=idempotency_key or uuid.uuid4().hex
            )
    except IntegrityError:  # clé d'idempotence prise entre-temps (course)
        existing = PaymentAttempt.objects.select_related("donation").filter(idempotency_key=idempotency_key).first()
        if existing is None:
            raise
        return existing.donation, existing, False

    return_url = f"{settings.DONATIONS_RETURN_URL}?don={donation.pk}"
    try:
        session = provider.create_checkout(
            CheckoutRequest(
                reference=donation.reference,
                amount=charged,
                description=f"Don — {fund.title}",
                return_url=return_url,
                cancel_url=f"{return_url}&annule=1",
                callback_url=f"{settings.DONATIONS_CALLBACK_BASE_URL}/api/v1/dons/webhooks/{provider.code}/",
                allocation_key=activation.allocation_key,
                customer_email=donation.donor_email,
            )
        )
    except ProviderError as exc:
        logger.warning("dons.checkout_echec reference=%s", donation.reference)
        with transaction.atomic():
            attempt.status = AttemptStatus.ECHOUE
            attempt.save(update_fields=["status", "updated_at"])
            donation_transition(
                donation=donation, to=DonationStatus.ECHOUE, source=StatusSource.CHECKOUT, note="provider"
            )
        raise ProviderUnavailable("Le service de paiement est indisponible. Réessayez dans un instant.") from exc

    with transaction.atomic():
        attempt.external_ref = session.external_ref
        attempt.checkout_url = session.checkout_url
        attempt.expires_at = session.expires_at
        attempt.raw_payload = session.raw
        attempt.status = AttemptStatus.EN_ATTENTE
        attempt.save(
            update_fields=["external_ref", "checkout_url", "expires_at", "raw_payload", "status", "updated_at"]
        )
        donation = donation_transition(donation=donation, to=DonationStatus.EN_ATTENTE, source=StatusSource.CHECKOUT)
    return donation, attempt, True


def donation_mark_returned(*, donation: Donation) -> Donation:
    """Premier retour du donateur sur la page de statut (santé du lien de retour). Idempotent."""
    if donation.returned_at is None:
        now = timezone.now()
        if Donation.objects.filter(pk=donation.pk, returned_at__isnull=True).update(returned_at=now):
            donation.returned_at = now
    return donation


# --- Machine à états ------------------------------------------------------------------------


@transaction.atomic
def donation_transition(*, donation: Donation, to: str, source: str, actor: Any = None, note: str = "") -> Donation:
    """Transition stricte et journalisée (SRS §8.4). Rester dans le même statut est sans effet."""
    locked = Donation.objects.select_for_update().get(pk=donation.pk)
    if locked.status == to:
        return locked
    if to not in DONATION_TRANSITIONS[locked.status]:
        raise ApplicationError(
            "Transition de statut interdite.", {"de": locked.status, "vers": to}, code="invalid_transition"
        )
    now = timezone.now()
    DonationStatusChange.objects.create(
        donation=locked, from_status=locked.status, to_status=to, source=source, actor=actor, note=note[:200]
    )
    locked.status = to
    locked.status_changed_at = now
    fields = ["status", "status_changed_at", "updated_at"]
    if to == DonationStatus.CONFIRME:
        locked.confirmed_at = now
        fields.append("confirmed_at")
        if locked.value_date is None:
            locked.value_date = timezone.localdate(now)
            fields.append("value_date")
        if locked.channel == DonationChannel.EN_LIGNE and not locked.receipt_number:
            fund_node = Fund.objects.select_related("node").get(pk=locked.fund_id).node
            locked.receipt_number = _receipt_number_next(node=fund_node, year=timezone.localdate().year)
            fields.append("receipt_number")
    locked.save(update_fields=fields)
    return locked


def _campaign_close_if_reached(*, fund_id: Any) -> None:
    """La collecte d'une campagne se ferme dès que l'objectif est atteint (décision du 27/09/2026)."""
    fund = Fund.objects.select_for_update().get(pk=fund_id)
    if fund.kind != FundKind.CAMPAGNE or not fund.goal_amount or fund.status != FundStatus.OUVERT:
        return
    raised = sum(
        Donation.objects.filter(fund=fund, status=DonationStatus.CONFIRME).values_list("net_amount", flat=True)
    )
    if raised >= fund.goal_amount:
        fund.status = FundStatus.CLOS
        fund.closed_at = timezone.now()
        fund.save(update_fields=["status", "closed_at", "updated_at"])
        audit_log(actor=None, action="dons.campagne_objectif_atteint", target=fund, node=fund.node)


@transaction.atomic
def payment_state_apply(*, attempt: PaymentAttempt, state: PaymentState, source: str) -> str:
    """Applique l'état **vérifié auprès de l'agrégateur**. Renvoie l'issue :
    ``confirme``, ``echoue``, ``expire``, ``en_attente``, ``doublon`` ou ``amount_mismatch``."""
    attempt = PaymentAttempt.objects.select_for_update().select_related("donation").get(pk=attempt.pk)
    donation = attempt.donation
    attempt.last_checked_at = timezone.now()
    attempt.save(update_fields=["last_checked_at", "updated_at"])

    if state.status == ProviderStatus.COMPLETED:
        if donation.status in (DonationStatus.CONFIRME, DonationStatus.REMBOURSE):
            return "doublon"
        if state.amount is not None and state.amount != donation.charged_amount:
            logger.warning("dons.montant_incoherent reference=%s", donation.reference)
            _incident_record(attempt=attempt, donation=donation, kind=IncidentKind.AMOUNT_MISMATCH,
                             reported_amount=state.amount)  # fmt: skip
            return "amount_mismatch"
        if donation.status not in (DonationStatus.INITIE, DonationStatus.EN_ATTENTE):
            # Paiement réussi après expiration ou échec : le fidèle est débité, le don n'est dans aucun
            # total. Incident persisté, à régulariser par la paroisse (intégration ou remboursement).
            logger.warning("dons.paiement_tardif reference=%s", donation.reference)
            _incident_record(attempt=attempt, donation=donation, kind=IncidentKind.LATE_PAYMENT,
                             reported_amount=state.amount, method=state.method)  # fmt: skip
            return "late_payment"
        updates = ["payment_method", "updated_at"]
        donation.payment_method = state.method or PaymentMethod.INCONNU
        if state.fee_amount is not None:
            donation.fee_amount = state.fee_amount
            donation.net_amount = max(donation.charged_amount - state.fee_amount, 0)
            donation.fee_is_actual = True
            updates += ["fee_amount", "net_amount", "fee_is_actual"]
        donation.save(update_fields=updates)
        if donation.status == DonationStatus.INITIE:
            donation_transition(donation=donation, to=DonationStatus.EN_ATTENTE, source=source)
        donation = donation_transition(donation=donation, to=DonationStatus.CONFIRME, source=source)
        attempt.status = AttemptStatus.REUSSI
        attempt.save(update_fields=["status", "updated_at"])
        _campaign_close_if_reached(fund_id=donation.fund_id)
        _receipt_email_queue(donation)
        return "confirme"

    if state.status in (ProviderStatus.FAILED, ProviderStatus.CANCELLED):
        if donation.status in (DonationStatus.INITIE, DonationStatus.EN_ATTENTE):
            donation_transition(donation=donation, to=DonationStatus.ECHOUE, source=source, note=state.status)
            attempt.status = AttemptStatus.ANNULE if state.status == ProviderStatus.CANCELLED else AttemptStatus.ECHOUE
            attempt.save(update_fields=["status", "updated_at"])
            return "echoue"
        return "doublon"

    if state.status == ProviderStatus.EXPIRED:
        if donation.status in (DonationStatus.INITIE, DonationStatus.EN_ATTENTE):
            donation_transition(donation=donation, to=DonationStatus.EXPIRE, source=source)
            attempt.status = AttemptStatus.EXPIRE
            attempt.save(update_fields=["status", "updated_at"])
            return "expire"
        return "doublon"
    return "en_attente"


def _incident_record(
    *, attempt: PaymentAttempt, donation: Donation, kind: str, reported_amount: int | None, method: str = ""
) -> PaymentIncident:
    """Persiste un incident de paiement (idempotent : une notification rejouée ne le duplique pas)."""
    incident, created = PaymentIncident.objects.get_or_create(
        attempt=attempt, kind=kind, defaults={"donation": donation, "reported_amount": reported_amount}
    )
    if created and method and method != PaymentMethod.INCONNU and donation.payment_method == PaymentMethod.INCONNU:
        Donation.objects.filter(pk=donation.pk).update(payment_method=method)
    return incident


def _receipt_email_queue(donation: Donation) -> None:
    """Don sans compte avec adresse : reçu simple par e-mail (le fidèle connecté le trouve dans « Mes dons »)."""
    if donation.donor_id or not donation.donor_email:
        return
    from apps.emails.services import email_queue

    email_queue(
        to=donation.donor_email,
        template="donations/recu_don",
        context={
            "recu_numero": donation.receipt_number,
            "reference": donation.reference,
            "fonds": donation.fund.title,
            "paroisse": donation.fund.node.name,
            "montant": donation.amount,
            "date": timezone.localtime(donation.status_changed_at or timezone.now()),
        },
    )
    Donation.objects.filter(pk=donation.pk).update(receipt_email_sent_at=timezone.now())


# --- Notifications de l'agrégateur (webhook / IPN) ------------------------------------------


def webhook_receive(*, provider_code: str, headers: dict[str, str], body: bytes) -> tuple[PaymentWebhookEvent, bool]:
    """Enregistre la notification et programme son traitement. Renvoie (événement, nouveau).

    Réponse rapide : la vérification de signature est locale ; le traitement (qui interroge
    l'agrégateur) part en tâche Celery après commit. Même corps reçu deux fois : doublon."""
    payload_hash = hashlib.sha256(provider_code.encode() + b"\x00" + body).hexdigest()
    existing = PaymentWebhookEvent.objects.filter(payload_hash=payload_hash).first()
    if existing is not None:
        return existing, False
    provider = get_provider(provider_code)
    try:
        state = provider.verify_callback(headers=headers, body=body)
    except InvalidSignature:
        logger.warning("dons.webhook_signature_invalide provider=%s", provider_code)
        event, created = PaymentWebhookEvent.objects.get_or_create(
            payload_hash=payload_hash,
            defaults={"provider": provider_code, "signature_valid": False, "status": WebhookStatus.REJETE,
                      "error_code": "invalid_signature", "processed_at": timezone.now()},
        )  # fmt: skip
        return event, created
    try:
        with transaction.atomic():
            event = PaymentWebhookEvent.objects.create(
                provider=provider_code,
                payload_hash=payload_hash,
                external_ref=state.external_ref[:120],
                reported_status=state.status[:20],
                signature_valid=True,
                payload=state.raw,
            )
            from apps.donations.tasks import donations_webhook_process_task

            transaction.on_commit(partial(donations_webhook_process_task.delay, event.pk))
    except IntegrityError:
        return PaymentWebhookEvent.objects.get(payload_hash=payload_hash), False
    return event, True


def webhook_process(*, event_id: int) -> PaymentWebhookEvent:
    """Traite une notification valide : le statut est **relu chez l'agrégateur** avant d'être appliqué."""
    event = PaymentWebhookEvent.objects.get(pk=event_id)
    if event.status != WebhookStatus.RECU:
        return event
    attempt = PaymentAttempt.objects.filter(provider=event.provider, external_ref=event.external_ref).first()
    if attempt is None:
        return _event_close(event, WebhookStatus.ERREUR, "unknown_reference")
    try:
        state = get_provider(event.provider).fetch_status(external_ref=event.external_ref)
    except ProviderError:
        # Reste « reçu » : la réconciliation reprendra le paiement.
        return _event_close(event, WebhookStatus.RECU, "provider_unavailable", processed=False)
    outcome = payment_state_apply(attempt=attempt, state=state, source=StatusSource.WEBHOOK)
    if outcome in ("amount_mismatch", "late_payment"):
        return _event_close(event, WebhookStatus.ERREUR, outcome)
    if outcome == "doublon":
        return _event_close(event, WebhookStatus.DOUBLON, "")
    return _event_close(event, WebhookStatus.TRAITE, "")


def _event_close(event: PaymentWebhookEvent, status: str, error: str, *, processed: bool = True) -> PaymentWebhookEvent:
    event.status = status
    event.error_code = error
    event.processed_at = timezone.now() if processed else None
    event.save(update_fields=["status", "error_code", "processed_at"])
    return event


# --- Réconciliation -------------------------------------------------------------------------


def donations_reconcile(*, now: datetime.datetime | None = None) -> dict[str, int]:
    """Tâche périodique : relit les paiements en attente, puis expire ceux qui ont dépassé le délai."""
    now = now or timezone.now()
    check_before = now - datetime.timedelta(minutes=settings.DONATIONS_PENDING_CHECK_MINUTES)
    expire_before = now - datetime.timedelta(hours=settings.DONATIONS_EXPIRE_HOURS)
    counts = {"verifies": 0, "confirmes": 0, "expires": 0, "erreurs": 0}
    pending = PaymentAttempt.objects.filter(
        donation__status__in=[DonationStatus.INITIE, DonationStatus.EN_ATTENTE],
        external_ref__isnull=False,
        created_at__lte=check_before,
    ).select_related("donation")
    for attempt in pending.iterator():
        if attempt.last_checked_at and attempt.last_checked_at > check_before:
            continue
        try:
            state = get_provider(attempt.provider).fetch_status(external_ref=attempt.external_ref or "")
        except ProviderError:
            counts["erreurs"] += 1
            continue
        counts["verifies"] += 1
        outcome = payment_state_apply(attempt=attempt, state=state, source=StatusSource.RECONCILIATION)
        counts["confirmes"] += int(outcome == "confirme")
        counts["expires"] += int(outcome == "expire")
    stale = Donation.objects.filter(
        channel=DonationChannel.EN_LIGNE,
        status__in=[DonationStatus.INITIE, DonationStatus.EN_ATTENTE],
        created_at__lte=expire_before,
    )
    for donation in stale.iterator():
        donation_transition(donation=donation, to=DonationStatus.EXPIRE, source=StatusSource.RECONCILIATION)
        PaymentAttempt.objects.filter(
            donation=donation, status__in=[AttemptStatus.CREE, AttemptStatus.EN_ATTENTE]
        ).update(status=AttemptStatus.EXPIRE)
        counts["expires"] += 1
    return counts


def payouts_sync(*, since: datetime.datetime | None = None) -> int:
    """Importe les reversements de l'agrégateur et les rapproche. Renvoie le nombre de nouveaux."""
    provider = get_provider()
    since = since or timezone.now() - datetime.timedelta(days=31)
    created = 0
    for data in provider.list_payouts(since=since):
        if Payout.objects.filter(provider=provider.code, external_ref=data.external_ref).exists():
            continue
        payout = payout_record(provider_code=provider.code, data=data)
        if payout is not None:
            created += 1
    return created


@transaction.atomic
def payout_record(*, provider_code: str, data: PayoutData) -> Payout | None:
    refs = [ref for ref, _, _ in data.lines]
    attempts = {
        a.external_ref: a
        for a in PaymentAttempt.objects.filter(provider=provider_code, external_ref__in=refs).select_related(
            "donation__fund__node"
        )
    }
    diocese = next((_diocese_of(a.donation.fund.node) for a in attempts.values()), None)
    if diocese is None:
        logger.warning("dons.reversement_sans_diocese ref=%s", data.external_ref)
        return None
    payout = Payout.objects.create(
        provider=provider_code,
        external_ref=data.external_ref,
        node=diocese,
        paid_at=data.paid_at,
        gross_amount=data.gross_amount,
        fee_amount=data.fee_amount,
        net_amount=data.net_amount,
    )
    PayoutLine.objects.bulk_create(
        [PayoutLine(payout=payout, external_ref=ref, amount=amount, fee_amount=fee, attempt=attempts.get(ref))
         for ref, amount, fee in data.lines]
    )  # fmt: skip
    return payout_reconcile(payout=payout)


def _diocese_of(node: Node) -> Node | None:
    if access.is_diocese(node):
        return node
    return hierarchy_selectors.node_ancestor_of_type(node=node, type_code="diocese")


@transaction.atomic
def payout_reconcile(*, payout: Payout) -> Payout:
    """Écart = lignes sans don confirmé correspondant, ou montants différents, ou total incohérent."""
    unmatched = 0
    expected_net = 0
    for line in payout.lines.select_related("attempt__donation"):
        donation = line.attempt.donation if line.attempt else None
        if donation is None or donation.status != DonationStatus.CONFIRME or line.amount != donation.charged_amount:
            unmatched += 1
            continue
        expected_net += line.amount - line.fee_amount
        if donation.payout_id != payout.pk:
            Donation.objects.filter(pk=donation.pk).update(payout=payout)
    payout.unmatched_count = unmatched
    payout.discrepancy_amount = payout.net_amount - expected_net
    payout.status = PayoutStatus.RAPPROCHE if unmatched == 0 and payout.discrepancy_amount == 0 else PayoutStatus.ECART
    payout.reconciled_at = timezone.now()
    payout.save(update_fields=["unmatched_count", "discrepancy_amount", "status", "reconciled_at", "updated_at"])
    audit_log(actor=None, action="dons.reversement_rapprochement", target=payout, node=payout.node,
              metadata={"statut": payout.status})  # fmt: skip
    return payout


def imperee_covers(*, fund: Fund, mass_date: datetime.date) -> bool:
    """Une messe entre dans une quête impérée si elle tombe dans sa période, ou si c'est la messe
    anticipée de la veille et que le diocèse l'a incluse."""
    if fund.starts_on is None:
        return True
    last = fund.ends_on or fund.starts_on
    if fund.starts_on <= mass_date <= last:
        return True
    return fund.messe_anticipee_incluse and mass_date == fund.starts_on - datetime.timedelta(days=1)


# --- Anonymat partiel (décision de revue du 27/09/2026) --------------------------------------

REVEAL_OFFICES = frozenset({"cure", "cure_in_solidum"})


@transaction.atomic
def donor_reveal(*, donation: Donation, actor: Any, reason: str) -> dict[str, Any]:
    """Le curé consulte, en cas de besoin, le nom d'un donateur anonyme. Motif obligatoire ; chaque
    consultation est journalisée (AuditEvent). Le nom reste masqué partout ailleurs."""
    node = donation.fund.node
    access.require_parish_level(actor, "dons.voir_donateurs", node)
    if not any(
        g.capability == "dons.voir_donateurs" and g.node_id == str(node.pk) and g.office in REVEAL_OFFICES
        for g in authz.grants(actor)
    ):
        raise PermissionDeniedError("Réservé au curé de la paroisse.", code="dons_forbidden")
    if donation.channel != DonationChannel.EN_LIGNE or not donation.anonymous:
        raise ApplicationError("Ce don n'est pas anonyme.", code="not_anonymous")
    motif = " ".join(reason.split())
    if len(motif) < 10:
        raise ApplicationError("Indiquez le motif de la consultation (10 caractères au moins).", code="reason_required")
    audit_log(actor=actor, action="dons.anonymat_consultation", target=donation, node=node,
              metadata={"reference": donation.reference, "motif": motif[:300]})  # fmt: skip
    name = None
    if donation.donor_id is not None:
        profile = getattr(donation.donor, "profile", None)
        name = f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip() or None
    return {"donation_id": donation.pk, "reference": donation.reference, "donateur": name,
            "sans_compte": donation.donor_id is None}  # fmt: skip


# --- Clôture mensuelle : verrou -------------------------------------------------------------


def month_open_check(*, node: Node, day: datetime.date) -> None:
    """Refuse une opération datée d'un mois clos (la correction passe par un ajustement)."""
    if MonthClosing.objects.filter(node=node, month=day.replace(day=1)).exists():
        raise ApplicationError(
            "Ce mois est clos : passez une écriture d'ajustement.", {"mois": f"{day:%Y-%m}"}, code="month_closed"
        )


# --- Quêtes en espèces ----------------------------------------------------------------------


@transaction.atomic
def cash_collection_create(
    *,
    actor: Any,
    node: Node,
    fund: Fund,
    mass_date: datetime.date,
    mass_label: str,
    amount: int,
    counter_one: str,
    counter_two: str,
    observation: str = "",
    place: PlaceOfWorship | None = None,
) -> CashCollection:
    access.require_parish_level(actor, "dons.saisir_quete", node)
    if fund.node_id != node.pk:
        raise ApplicationError("Ce fonds n'appartient pas à la paroisse.", code="fund_outside")
    if fund.status == FundStatus.BROUILLON:
        raise ApplicationError("Ce fonds n'est pas publié.", code="fund_not_open")
    if place is not None and place.node_id != node.pk:
        raise ApplicationError("Ce lieu n'appartient pas à la paroisse.", code="place_outside")
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= MAX_CASH_AMOUNT:
        raise ApplicationError("Montant invalide.", code="invalid_amount")
    if mass_date > timezone.localdate():
        raise ApplicationError("La messe ne peut pas être à venir.", code="future_mass")
    month_open_check(node=node, day=mass_date)
    if fund.kind == FundKind.QUETE_IMPEREE and not imperee_covers(fund=fund, mass_date=mass_date):
        raise ApplicationError(
            "Cette messe n'entre pas dans la quête impérée.", {"messe_anticipee_incluse": fund.messe_anticipee_incluse},
            code="mass_outside_imperee",
        )  # fmt: skip
    one, two = counter_one.strip(), counter_two.strip()
    if not one or not two or one.casefold() == two.casefold():
        raise ApplicationError("La quête est comptée par deux personnes distinctes.", code="two_counters_required")
    collection = CashCollection.objects.create(
        node=node,
        fund=fund,
        place=place,
        mass_date=mass_date,
        mass_label=mass_label,
        amount=amount,
        counter_one=one,
        counter_two=two,
        observation=observation,
        entered_by=actor,
    )
    audit_log(actor=actor, action="dons.quete_saisie", target=collection, node=node)
    return collection


def _require_cash_validator(collection: CashCollection, actor: Any) -> None:
    node = collection.node
    if not (
        access.parish_level(actor, "dons.saisir_quete", node) or access.parish_level(actor, "dons.gerer_fonds", node)
    ):
        raise PermissionDeniedError("Vous ne validez pas les quêtes de cette paroisse.", code="dons_forbidden")
    authz.mfa_check(actor)
    if collection.entered_by_id == actor.pk:
        raise ApplicationError("La validation revient à une autre personne que la saisie.", code="four_eyes")
    if collection.status != CashCollectionStatus.SAISIE:
        raise ApplicationError("Cette saisie est déjà traitée.", code="invalid_transition")


@transaction.atomic
def cash_collection_validate(*, collection: CashCollection, actor: Any) -> CashCollection:
    collection = CashCollection.objects.select_for_update().select_related("node", "fund").get(pk=collection.pk)
    _require_cash_validator(collection, actor)
    month_open_check(node=collection.node, day=collection.mass_date)
    now = timezone.now()
    collection.status = CashCollectionStatus.VALIDEE
    collection.validated_by = actor
    collection.validated_at = now
    collection.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    donation = Donation.objects.create(
        reference=_new_reference(),
        fund=collection.fund,
        amount=collection.amount,
        fee_amount=0,
        charged_amount=collection.amount,
        net_amount=collection.amount,
        anonymous=True,
        channel=DonationChannel.ESPECES,
        payment_method=PaymentMethod.ESPECES,
        status=DonationStatus.CONFIRME,
        status_changed_at=now,
        confirmed_at=now,
        value_date=collection.mass_date,
        place_id=collection.place_id,
        source=None,
        cash_collection=collection,
    )
    DonationStatusChange.objects.create(
        donation=donation, from_status=DonationStatus.INITIE, to_status=DonationStatus.CONFIRME,
        source=StatusSource.STAFF, actor=actor, note="quête en espèces validée",
    )  # fmt: skip
    audit_log(actor=actor, action="dons.quete_validation", target=collection, node=collection.node)
    return collection


@transaction.atomic
def cash_collection_reject(*, collection: CashCollection, actor: Any, reason: str) -> CashCollection:
    collection = CashCollection.objects.select_for_update().select_related("node").get(pk=collection.pk)
    _require_cash_validator(collection, actor)
    if not reason.strip():
        raise ApplicationError("Le motif est obligatoire.", code="reason_required")
    collection.status = CashCollectionStatus.REJETEE
    collection.validated_by = actor
    collection.validated_at = timezone.now()
    collection.rejection_reason = reason.strip()[:300]
    collection.save(update_fields=["status", "validated_by", "validated_at", "rejection_reason", "updated_at"])
    audit_log(actor=actor, action="dons.quete_rejet", target=collection, node=collection.node)
    return collection


# --- Remboursement --------------------------------------------------------------------------


@transaction.atomic
def donation_refund(*, donation: Donation, actor: Any, note: str = "") -> Donation:
    """Constate un remboursement fait chez l'agrégateur (le don sort des totaux)."""
    access.require_parish_level(actor, "dons.gerer_fonds", donation.fund.node)
    if donation.channel != DonationChannel.EN_LIGNE:
        raise ApplicationError("Une quête en espèces ne se rembourse pas ici.", code="not_online")
    donation.refresh_from_db(fields=["status"])
    if donation.status != DonationStatus.CONFIRME:
        raise ApplicationError("Seul un don confirmé se rembourse.", code="invalid_transition")
    donation = donation_transition(
        donation=donation, to=DonationStatus.REMBOURSE, source=StatusSource.STAFF, actor=actor, note=note
    )
    # Le mois du don reste figé : le remboursement est une ligne négative du mois courant.
    DonationAdjustment.objects.create(
        node=donation.fund.node, fund=donation.fund, donation=donation, kind=AdjustmentKind.REMBOURSEMENT,
        channel=donation.channel, source=donation.source, payment_method=donation.payment_method,
        place_id=donation.place_id, amount=-donation.amount, net_amount=-donation.net_amount,
        value_date=timezone.localdate(), reason=(note or "Remboursement")[:300], created_by=actor,
    )  # fmt: skip
    audit_log(actor=actor, action="dons.remboursement", target=donation, node=donation.fund.node,
              metadata={"reference": donation.reference})  # fmt: skip
    return donation


def export_logged(*, actor: Any, node: Node, rows: int, fmt: str) -> None:
    """Un export comptable est une action sensible : il est journalisé (sans montant ni nom)."""
    audit_log(actor=actor, action="dons.export", target=node, node=node, metadata={"lignes": rows, "format": fmt})


# --- Conservation (loi 2008-12) -------------------------------------------------------------


def donor_emails_purge(*, now: datetime.datetime | None = None) -> int:
    """Efface l'adresse des dons sans compte, 90 jours après la fin du paiement."""
    now = now or timezone.now()
    limit = now - datetime.timedelta(days=settings.DONATIONS_DONOR_EMAIL_RETENTION_DAYS)
    return (
        Donation.objects.exclude(donor_email="")
        .filter(status_changed_at__lte=limit)
        .exclude(status__in=[DonationStatus.INITIE, DonationStatus.EN_ATTENTE])
        .update(donor_email="")
    )
