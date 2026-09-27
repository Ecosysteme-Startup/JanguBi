"""Dons et quêtes (ADR-017 ; cadrage DONS-00 §3). Schéma seulement : les règles sont dans ``services``.

Numerisen ne détient jamais les fonds : le paiement se fait chez un agrégateur agréé BCEAO,
sur le compte de l'archidiocèse (H1). Ce module n'enregistre que des intentions de don, leur
confirmation par l'agrégateur et les saisies de quêtes en espèces.
"""

import uuid

from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel
from apps.donations.enums import (
    AttemptStatus,
    CashCollectionStatus,
    DonationChannel,
    DonationStatus,
    FundDestination,
    FundKind,
    FundStatus,
    PaymentMethod,
    PayoutStatus,
    StatusSource,
    WebhookStatus,
)
from apps.donations.fields import EncryptedTextField


class DonationActivation(BaseModel):
    """Activation de la collecte sur une paroisse (H4 : autorisation écrite de l'Ordinaire, c. 1265)."""

    node = models.OneToOneField("hierarchy.Node", on_delete=models.CASCADE, related_name="donation_activation")
    enabled = models.BooleanField(_("collecte active"), default=False)
    authorization_ref = models.CharField(_("référence de l'autorisation"), max_length=120, blank=True, default="")
    authorization_date = models.DateField(_("date de l'autorisation"), null=True, blank=True)
    authorization_text = models.CharField(
        _("mention affichée"),
        max_length=300,
        blank=True,
        default="",
        help_text=_("Ex. « Collecte autorisée par l'Archevêché de Dakar (réf. …) ». Vide : texte par défaut."),
    )
    # H1 : l'archidiocèse est titulaire du compte ; la clé d'affectation identifie la paroisse chez l'agrégateur.
    allocation_key = models.CharField(_("clé d'affectation"), max_length=64, blank=True, default="")

    class Meta:
        verbose_name = _("activation des dons")
        verbose_name_plural = _("activations des dons")

    def __str__(self) -> str:
        return f"Dons {'actifs' if self.enabled else 'inactifs'} ({self.node_id})"


class Fund(BaseModel):
    """Fonds : un don ne sert qu'à son fonds (c. 1267 §3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="donation_funds")
    kind = models.CharField(_("type"), max_length=30, choices=FundKind.choices)
    destination = models.CharField(
        _("destination"), max_length=10, choices=FundDestination.choices, default=FundDestination.PAROISSE
    )
    title = models.CharField(_("titre"), max_length=160)
    description = models.TextField(_("usage des fonds"), blank=True, default="")
    starts_on = models.DateField(_("début"), null=True, blank=True)
    ends_on = models.DateField(_("fin"), null=True, blank=True)
    goal_amount = models.PositiveIntegerField(_("objectif (FCFA)"), null=True, blank=True)
    status = models.CharField(max_length=10, choices=FundStatus.choices, default=FundStatus.BROUILLON, db_index=True)
    # Quête impérée : fonds diocésain (parent) décliné sur chaque paroisse concernée.
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="parish_funds")
    decided_by = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_by_office = models.CharField(_("office qui décide"), max_length=60, blank=True, default="")
    authorization_ref = models.CharField(_("référence de l'autorisation"), max_length=120, blank=True, default="")
    image = models.ForeignKey("files.File", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("fonds")
        verbose_name_plural = _("fonds")
        ordering = ["-created_at"]
        constraints = [
            # c. 1266 : la quête impérée est reversée à la curie.
            models.CheckConstraint(
                condition=~Q(kind=FundKind.QUETE_IMPEREE) | Q(destination=FundDestination.CURIE),
                name="dons_fund_imperee_curie",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True) | Q(starts_on__isnull=True) | Q(ends_on__gte=F("starts_on")),
                name="dons_fund_period",
            ),
            models.CheckConstraint(
                condition=Q(goal_amount__isnull=True) | Q(goal_amount__gt=0), name="dons_fund_goal_positive"
            ),
        ]
        indexes = [models.Index(fields=["node", "status"], name="dons_fund_node_status_idx")]

    def __str__(self) -> str:
        return self.title


class FundUpdate(BaseModel):
    """Nouvelle publiée sur une campagne (« mises à jour du curé »)."""

    fund = models.ForeignKey(Fund, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey("users.BaseUser", on_delete=models.SET_NULL, null=True, related_name="+")
    body = models.TextField(_("texte"), max_length=2000)

    class Meta:
        verbose_name = _("nouvelle de campagne")
        verbose_name_plural = _("nouvelles de campagne")
        ordering = ["-created_at"]


class CashCollection(BaseModel):
    """Quête en espèces d'une messe, comptée par deux personnes et validée par une seconde."""

    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="cash_collections")
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="cash_collections")
    place = models.ForeignKey(
        "hierarchy.PlaceOfWorship", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    mass_date = models.DateField(_("date de la messe"))
    mass_label = models.CharField(_("messe"), max_length=120)
    amount = models.PositiveIntegerField(_("montant compté (FCFA)"))
    counter_one = models.CharField(_("premier compteur"), max_length=120)
    counter_two = models.CharField(_("second compteur"), max_length=120)
    observation = models.CharField(_("observation"), max_length=500, blank=True, default="")
    status = models.CharField(
        max_length=10, choices=CashCollectionStatus.choices, default=CashCollectionStatus.SAISIE, db_index=True
    )
    entered_by = models.ForeignKey("users.BaseUser", on_delete=models.PROTECT, related_name="+")
    validated_by = models.ForeignKey(
        "users.BaseUser", on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True, default="")

    class Meta:
        verbose_name = _("quête en espèces")
        verbose_name_plural = _("quêtes en espèces")
        ordering = ["-mass_date", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="dons_cash_amount_positive"),
            # La validation est faite par une autre personne que la saisie.
            models.CheckConstraint(
                condition=Q(validated_by__isnull=True) | ~Q(validated_by=F("entered_by")),
                name="dons_cash_four_eyes",
            ),
        ]


class Payout(BaseModel):
    """Reversement de l'agrégateur sur le compte de l'archidiocèse (H1)."""

    provider = models.CharField(max_length=30)
    external_ref = models.CharField(max_length=120)
    node = models.ForeignKey("hierarchy.Node", on_delete=models.PROTECT, related_name="donation_payouts")
    paid_at = models.DateTimeField()
    gross_amount = models.PositiveIntegerField()
    fee_amount = models.PositiveIntegerField(default=0)
    net_amount = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=PayoutStatus.choices, default=PayoutStatus.RECU, db_index=True)
    discrepancy_amount = models.IntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    reconciled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("reversement")
        verbose_name_plural = _("reversements")
        ordering = ["-paid_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_ref"], name="dons_payout_unique_ref"),
        ]


class Donation(BaseModel):
    """Un don. Le fonds est immuable (c. 1267 §3) ; les montants sont des entiers en FCFA."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=20, unique=True)
    fund = models.ForeignKey(Fund, on_delete=models.PROTECT, related_name="donations")
    amount = models.PositiveIntegerField(_("don (FCFA)"))
    fees_covered = models.BooleanField(_("frais couverts par le donateur"), default=False)
    fee_amount = models.PositiveIntegerField(_("frais (FCFA)"), default=0)
    charged_amount = models.PositiveIntegerField(_("montant payé (FCFA)"))
    net_amount = models.PositiveIntegerField(_("montant affecté au fonds (FCFA)"))
    anonymous = models.BooleanField(_("don anonyme"), default=False)
    donor = models.ForeignKey(
        "users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="donations"
    )
    # Don sans compte : pour le seul envoi du reçu ; effacée 90 jours après la fin du paiement.
    donor_email = models.EmailField(blank=True, default="")
    channel = models.CharField(max_length=10, choices=DonationChannel.choices, default=DonationChannel.EN_LIGNE)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.INCONNU)
    status = models.CharField(
        max_length=12, choices=DonationStatus.choices, default=DonationStatus.INITIE, db_index=True
    )
    status_changed_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    cash_collection = models.OneToOneField(
        CashCollection, on_delete=models.PROTECT, null=True, blank=True, related_name="donation"
    )
    payout = models.ForeignKey(Payout, on_delete=models.SET_NULL, null=True, blank=True, related_name="donations")
    receipt_email_sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("don")
        verbose_name_plural = _("dons")
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="dons_donation_amount_positive"),
            models.CheckConstraint(condition=Q(net_amount__lte=F("charged_amount")), name="dons_donation_net_le_charged"),
            models.CheckConstraint(
                condition=Q(channel=DonationChannel.EN_LIGNE) | Q(cash_collection__isnull=False),
                name="dons_donation_cash_has_collection",
            ),
        ]
        indexes = [
            models.Index(fields=["fund", "status"], name="dons_donation_fund_status_idx"),
            models.Index(fields=["donor", "status"], name="dons_donation_donor_idx"),
        ]

    def __str__(self) -> str:
        return self.reference


class DonationStatusChange(models.Model):
    """Journal immuable des transitions d'un don."""

    donation = models.ForeignKey(Donation, on_delete=models.CASCADE, related_name="status_changes")
    from_status = models.CharField(max_length=12, choices=DonationStatus.choices)
    to_status = models.CharField(max_length=12, choices=DonationStatus.choices)
    source = models.CharField(max_length=15, choices=StatusSource.choices)
    actor = models.ForeignKey("users.BaseUser", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    note = models.CharField(max_length=200, blank=True, default="")
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("changement de statut d'un don")
        verbose_name_plural = _("changements de statut des dons")
        ordering = ["at", "id"]


class PaymentAttempt(BaseModel):
    """Tentative de paiement chez l'agrégateur. La clé d'idempotence évite un double checkout."""

    donation = models.ForeignKey(Donation, on_delete=models.CASCADE, related_name="attempts")
    provider = models.CharField(max_length=30)
    external_ref = models.CharField(max_length=120, null=True, blank=True)
    idempotency_key = models.CharField(max_length=80, unique=True)
    checkout_url = models.URLField(max_length=500, blank=True, default="")
    status = models.CharField(max_length=12, choices=AttemptStatus.choices, default=AttemptStatus.CREE, db_index=True)
    raw_payload = EncryptedTextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("tentative de paiement")
        verbose_name_plural = _("tentatives de paiement")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_ref"],
                condition=Q(external_ref__isnull=False),
                name="dons_attempt_unique_external_ref",
            ),
        ]


class PaymentWebhookEvent(models.Model):
    """Notification reçue de l'agrégateur (IPN). L'empreinte du corps rend le rejeu inoffensif."""

    provider = models.CharField(max_length=30)
    payload_hash = models.CharField(max_length=64, unique=True)
    external_ref = models.CharField(max_length=120, blank=True, default="", db_index=True)
    # Statut annoncé par la notification, jamais cru seul : le traitement contre-vérifie.
    reported_status = models.CharField(max_length=20, blank=True, default="")
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=WebhookStatus.choices, default=WebhookStatus.RECU, db_index=True)
    error_code = models.CharField(max_length=60, blank=True, default="")
    payload = EncryptedTextField(blank=True, default="")
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("notification de paiement")
        verbose_name_plural = _("notifications de paiement")
        ordering = ["-received_at"]


class PayoutLine(models.Model):
    """Une transaction incluse dans un reversement, selon le relevé de l'agrégateur."""

    payout = models.ForeignKey(Payout, on_delete=models.CASCADE, related_name="lines")
    external_ref = models.CharField(max_length=120)
    amount = models.PositiveIntegerField()
    fee_amount = models.PositiveIntegerField(default=0)
    attempt = models.ForeignKey(PaymentAttempt, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = _("ligne de reversement")
        verbose_name_plural = _("lignes de reversement")
