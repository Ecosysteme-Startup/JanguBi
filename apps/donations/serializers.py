from typing import Any

from django.conf import settings
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.donations.enums import (
    CashCollectionStatus,
    DonationChannel,
    DonationSource,
    DonationStatus,
    FundKind,
    FundStatus,
    IncidentResolution,
    IncidentStatus,
    RemittanceMode,
    RemittanceStatus,
)
from apps.donations.models import (
    CashCollection,
    CashDeposit,
    CuriaRemittance,
    Donation,
    DonationActivation,
    DonationAdjustment,
    Fund,
    FundUpdate,
    MonthClosing,
    PaymentIncident,
    Payout,
)
from apps.donations.selectors import donor_label, fund_updates

PARISH_KINDS = [c for c in FundKind.choices if c[0] != FundKind.QUETE_IMPEREE]
ISSUE_KINDS = [
    ("paiement_en_attente", "Paiement en attente depuis plus de 24 h"),
    ("quete_non_validee", "Quête en espèces non validée depuis 7 jours"),
    ("reversement_ecart", "Reversement avec écart"),
]
EXPORT_FILES = [("csv", "CSV"), ("xlsx", "Excel")]


def _full_name(user: Any) -> str:
    profile = getattr(user, "profile", None)
    return f"{getattr(profile, 'first_name', '')} {getattr(profile, 'last_name', '')}".strip()


# --- Entrées --------------------------------------------------------------------------------


class NodeQuerySerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse (ou diocèse pour les quêtes impérées)")


class CheckoutInputSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField()
    amount = serializers.IntegerField(help_text="Montant du don en FCFA (entier)")
    fees_covered = serializers.BooleanField(default=False, help_text="Le donateur couvre les frais (décoché par défaut)")
    anonymous = serializers.BooleanField(default=False)
    email = serializers.EmailField(
        required=False, allow_blank=True, default="", help_text="Sans compte seulement : envoi du reçu, effacé après 90 jours"
    )
    source = serializers.ChoiceField(  # type: ignore[assignment]  # champ nommé « source » (API)
        choices=DonationSource.choices, required=False, default=DonationSource.INCONNU,
        help_text="Canal d'entrée relayé par la page de don (paramètre ?src= de l'URL ouverte par l'app)",
    )  # fmt: skip
    place_id = serializers.IntegerField(
        required=False, allow_null=True, default=None,
        help_text="Lieu de culte (paramètre ?lieu= du QR code) ; sinon le lieu du fonds",
    )  # fmt: skip


class MyDonationsFilterSerializer(serializers.Serializer):
    fund = serializers.UUIDField(required=False)
    year = serializers.IntegerField(required=False, min_value=2020, max_value=2100)


class YearQuerySerializer(serializers.Serializer):
    year = serializers.IntegerField(required=False, min_value=2020, max_value=2100)


class FundListFilterSerializer(NodeQuerySerializer):
    status = serializers.ChoiceField(choices=FundStatus.choices, required=False)
    kind = serializers.ChoiceField(choices=FundKind.choices, required=False)


class FundCreateInputSerializer(serializers.Serializer):
    node = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=PARISH_KINDS)
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    starts_on = serializers.DateField(required=False, allow_null=True, default=None)
    ends_on = serializers.DateField(required=False, allow_null=True, default=None)
    goal_amount = serializers.IntegerField(required=False, allow_null=True, default=None, min_value=1)
    authorization_ref = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)
    image_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    place_id = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text="Lieu de culte propre au fonds (campagne d'une chapelle)"
    )


class FundUpdateInputSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160, required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    starts_on = serializers.DateField(required=False, allow_null=True)
    ends_on = serializers.DateField(required=False, allow_null=True)
    goal_amount = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    authorization_ref = serializers.CharField(required=False, allow_blank=True, max_length=120)
    image_id = serializers.IntegerField(required=False, allow_null=True)
    place_id = serializers.IntegerField(required=False, allow_null=True)


class FundNewsInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=2000)


class MonthQuerySerializer(NodeQuerySerializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", required=False, help_text="AAAA-MM (défaut : mois courant)")


class OperationsFilterSerializer(NodeQuerySerializer):
    fund = serializers.UUIDField(required=False)
    status = serializers.ChoiceField(choices=DonationStatus.choices, required=False)
    channel = serializers.ChoiceField(choices=DonationChannel.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class RefundInputSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CashCollectionFilterSerializer(NodeQuerySerializer):
    status = serializers.ChoiceField(choices=CashCollectionStatus.choices, required=False)


class CashCollectionInputSerializer(serializers.Serializer):
    node = serializers.UUIDField()
    fund_id = serializers.UUIDField()
    place_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    mass_date = serializers.DateField()
    mass_label = serializers.CharField(max_length=120, help_text="Ex. « Messe de 10 h »")
    amount = serializers.IntegerField(min_value=1)
    counter_one = serializers.CharField(max_length=120)
    counter_two = serializers.CharField(max_length=120)
    observation = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CashRejectInputSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=300)


class PeriodQuerySerializer(NodeQuerySerializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["date_to"] < attrs["date_from"]:
            raise serializers.ValidationError({"date_to": "La fin doit suivre le début."})
        return attrs


class ExportQuerySerializer(PeriodQuerySerializer):
    fund = serializers.UUIDField(required=False)
    # « format » est réservé par DRF (négociation de contenu) : on nomme le paramètre « fichier ».
    fichier = serializers.ChoiceField(choices=EXPORT_FILES, default="csv")


class ImpereeCreateInputSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Diocèse")
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=5000)
    starts_on = serializers.DateField(help_text="Date de la quête")
    ends_on = serializers.DateField(required=False, allow_null=True, default=None)
    parish_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_null=True, default=None,
        help_text="Paroisses concernées (défaut : toutes les paroisses du diocèse où la collecte est active)",
    )  # fmt: skip
    authorization_ref = serializers.CharField(required=False, allow_blank=True, default="", max_length=120)
    remit_by = serializers.DateField(
        required=False, allow_null=True, default=None,
        help_text="Échéance de remise des espèces à la curie (défaut : sept jours après la quête)",
    )  # fmt: skip
    messe_anticipee_incluse = serializers.BooleanField(
        default=False, help_text="La quête de la messe anticipée de la veille au soir fait partie de la quête impérée"
    )


class MassFundsQuerySerializer(NodeQuerySerializer):
    date = serializers.DateField(help_text="Date de la messe")


class DonorRevealInputSerializer(serializers.Serializer):
    motif = serializers.CharField(min_length=10, max_length=300, help_text="Obligatoire, journalisé")


class DonorRevealSerializer(serializers.Serializer):
    donation_id = serializers.UUIDField()
    reference = serializers.CharField()
    donateur = serializers.CharField(allow_null=True, help_text="null : don sans compte (aucun nom connu)")
    sans_compte = serializers.BooleanField()


class CashDepositInputSerializer(serializers.Serializer):
    node = serializers.UUIDField(help_text="Paroisse")
    collection_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1,
                                           help_text="Quêtes validées incluses dans le dépôt")  # fmt: skip
    deposited_on = serializers.DateField()
    bank_label = serializers.CharField(max_length=120, help_text="Banque et compte")
    slip_number = serializers.CharField(max_length=60, help_text="Numéro de bordereau")
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class RemittanceInputSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField(help_text="Quête impérée de la paroisse (déclinaison paroissiale)")
    amount = serializers.IntegerField(min_value=1)
    remitted_on = serializers.DateField()
    mode = serializers.ChoiceField(choices=RemittanceMode.choices, default=RemittanceMode.ESPECES)
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")


class RemittanceFilterSerializer(NodeQuerySerializer):
    status = serializers.ChoiceField(choices=RemittanceStatus.choices, required=False)


class MonthClosingInputSerializer(NodeQuerySerializer):
    month = serializers.RegexField(r"^\d{4}-(0[1-9]|1[0-2])$", help_text="AAAA-MM, mois écoulé")


class AdjustmentInputSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField()
    channel = serializers.ChoiceField(choices=DonationChannel.choices)
    amount = serializers.IntegerField(help_text="FCFA, signé : négatif pour retirer, jamais nul")
    reason = serializers.CharField(max_length=300)


class IncidentFilterSerializer(NodeQuerySerializer):
    status = serializers.ChoiceField(choices=IncidentStatus.choices, required=False)


class IncidentResolveInputSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=IncidentResolution.choices)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")


class ActivationInputSerializer(serializers.Serializer):
    node = serializers.UUIDField()
    enabled = serializers.BooleanField()
    authorization_ref = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    authorization_date = serializers.DateField(required=False, allow_null=True, default=None)
    authorization_text = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    allocation_key = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    receipt_prefix = serializers.RegexField(
        r"^[A-Za-z0-9]{0,8}$", required=False, allow_blank=True, default="", help_text="Ex. « SD » → SD-2026-00147"
    )


# --- Sorties --------------------------------------------------------------------------------


class NodeBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    city = serializers.CharField()


class FundBriefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    kind = serializers.CharField()


class PlaceBriefSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class PublicFundSerializer(serializers.ModelSerializer):
    raised = serializers.IntegerField(read_only=True, help_text="Montant affecté (dons confirmés), FCFA")
    image_url = serializers.SerializerMethodField()
    place = PlaceBriefSerializer(allow_null=True, read_only=True)

    class Meta:
        model = Fund
        fields = ["id", "kind", "destination", "title", "description", "starts_on", "ends_on", "goal_amount",
                  "raised", "status", "image_url", "place", "messe_anticipee_incluse"]  # fmt: skip

    def get_image_url(self, obj: Fund) -> str | None:
        return obj.image.url if obj.image and obj.image.is_valid else None


class FundNewsSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = FundUpdate
        fields = ["id", "body", "created_at", "author_name"]

    def get_author_name(self, obj: FundUpdate) -> str:
        return _full_name(obj.author) if obj.author else ""


class PublicFundDetailSerializer(PublicFundSerializer):
    parish = NodeBriefSerializer(source="node")
    updates = serializers.SerializerMethodField()

    class Meta(PublicFundSerializer.Meta):
        fields = [*PublicFundSerializer.Meta.fields, "parish", "updates"]

    @extend_schema_field(FundNewsSerializer(many=True))
    def get_updates(self, obj: Fund) -> Any:
        return FundNewsSerializer(fund_updates(fund=obj)[:20], many=True).data


class AuthorizationSerializer(serializers.Serializer):
    reference = serializers.CharField()
    date = serializers.DateField(allow_null=True)
    text = serializers.CharField()


class PublicParishSerializer(serializers.Serializer):
    parish = NodeBriefSerializer()
    enabled = serializers.BooleanField()
    authorization = AuthorizationSerializer(allow_null=True)
    suggested_amounts = serializers.ListField(child=serializers.IntegerField())
    min_amount = serializers.IntegerField()
    max_amount = serializers.IntegerField()
    fee_rate_bp = serializers.IntegerField(help_text="Frais estimés en points de base (200 = 2 %)")
    funds = PublicFundSerializer(many=True)


def authorization_payload(activation: DonationActivation | None) -> dict[str, Any] | None:
    if activation is None:
        return None
    text = activation.authorization_text or (
        f"Collecte autorisée par l'Ordinaire (réf. {activation.authorization_ref})."
        if activation.authorization_ref
        else ""
    )
    return {"reference": activation.authorization_ref, "date": activation.authorization_date, "text": text}


def amounts_payload() -> dict[str, Any]:
    return {
        "suggested_amounts": settings.DONATIONS_SUGGESTED_AMOUNTS,
        "min_amount": settings.DONATIONS_MIN_AMOUNT,
        "max_amount": settings.DONATIONS_MAX_AMOUNT,
        "fee_rate_bp": settings.DONATIONS_FEE_RATE_BP,
    }


class CheckoutOutputSerializer(serializers.Serializer):
    donation_id = serializers.UUIDField(source="donation.id")
    reference = serializers.CharField(source="donation.reference")
    status = serializers.CharField(source="donation.status")
    checkout_url = serializers.CharField(source="attempt.checkout_url", help_text="Page de paiement de l'agrégateur")
    amount = serializers.IntegerField(source="donation.amount")
    fee_amount = serializers.IntegerField(source="donation.fee_amount")
    charged_amount = serializers.IntegerField(source="donation.charged_amount")
    net_amount = serializers.IntegerField(source="donation.net_amount")


class DonationStatusSerializer(serializers.ModelSerializer):
    """Statut d'un don après le retour du navigateur : aucune donnée sur le donateur."""

    fund = FundBriefSerializer()
    parish = serializers.CharField(source="fund.node.name")

    class Meta:
        model = Donation
        fields = ["id", "reference", "receipt_number", "status", "fund", "parish", "amount", "fees_covered",
                  "charged_amount", "confirmed_at"]  # fmt: skip


class MyDonationSerializer(serializers.ModelSerializer):
    fund = FundBriefSerializer()
    parish = serializers.CharField(source="fund.node.name")
    receipt_available = serializers.SerializerMethodField()

    class Meta:
        model = Donation
        fields = ["id", "reference", "receipt_number", "fund", "parish", "amount", "fee_amount", "fees_covered", "charged_amount",
                  "status", "channel", "payment_method", "anonymous", "created_at", "confirmed_at",
                  "receipt_available"]  # fmt: skip

    def get_receipt_available(self, obj: Donation) -> bool:
        return obj.status == DonationStatus.CONFIRME


class DonorFundTotalSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField()
    title = serializers.CharField()
    parish = serializers.CharField()
    total = serializers.IntegerField()
    count = serializers.IntegerField()


class DonorSummarySerializer(serializers.Serializer):
    year = serializers.IntegerField()
    total = serializers.IntegerField()
    count = serializers.IntegerField()
    by_fund = DonorFundTotalSerializer(many=True)


class StaffFundSerializer(PublicFundSerializer):
    donations_count = serializers.IntegerField(read_only=True)
    node_id = serializers.UUIDField()
    parent_id = serializers.UUIDField(allow_null=True)

    class Meta(PublicFundSerializer.Meta):
        fields = [*PublicFundSerializer.Meta.fields, "node_id", "parent_id", "donations_count", "decided_by_office",
                  "authorization_ref", "published_at", "closed_at", "created_at"]  # fmt: skip


class SummaryFundSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField()
    title = serializers.CharField()
    kind = serializers.CharField()
    destination = serializers.CharField(help_text="paroisse ou curie (quête impérée)")
    total = serializers.IntegerField()
    count = serializers.IntegerField()


class SummaryMethodSerializer(serializers.Serializer):
    method = serializers.CharField()
    total = serializers.IntegerField()
    count = serializers.IntegerField()


class SummaryDaySerializer(serializers.Serializer):
    date = serializers.DateField(help_text="Date de valeur (jour de la messe pour les espèces)")
    online = serializers.IntegerField()
    cash = serializers.IntegerField()
    total = serializers.IntegerField()


class SummaryDestinationSerializer(serializers.Serializer):
    paroisse = serializers.IntegerField()
    curie = serializers.IntegerField()


class ParishSummarySerializer(serializers.Serializer):
    month = serializers.DateField()
    total = serializers.IntegerField(help_text="Affecté ce mois (date de valeur), remboursements déduits")
    online = serializers.IntegerField()
    cash = serializers.IntegerField()
    fees = serializers.IntegerField()
    count = serializers.IntegerField(help_text="Obsolète : additionne dons en ligne et quêtes. Utiliser les deux champs suivants.")
    online_count = serializers.IntegerField(help_text="Dons en ligne")
    cash_collections_count = serializers.IntegerField(help_text="Quêtes en espèces validées")
    pending_count = serializers.IntegerField(help_text="Paiements lancés ce mois encore en attente")
    pending_oldest_at = serializers.DateTimeField(allow_null=True)
    cash_to_validate = serializers.IntegerField()
    closed = serializers.BooleanField(help_text="Mois clos : aucune opération ne s'y ajoute plus")
    closed_at = serializers.DateTimeField(allow_null=True)
    by_destination = SummaryDestinationSerializer()
    by_fund = SummaryFundSerializer(many=True)
    by_method = SummaryMethodSerializer(many=True)
    daily = SummaryDaySerializer(many=True)


class OperationSerializer(serializers.ModelSerializer):
    """Opération vue par la paroisse. Nom seulement avec ``dons.voir_donateurs`` et hors anonymat."""

    fund = FundBriefSerializer()
    donor = serializers.SerializerMethodField()
    place = PlaceBriefSerializer(allow_null=True, read_only=True)

    class Meta:
        model = Donation
        fields = ["id", "reference", "receipt_number", "fund", "amount", "fee_amount", "fee_is_actual", "charged_amount",
                  "net_amount", "channel", "source", "payment_method", "place", "status", "created_at", "confirmed_at",
                  "value_date", "anonymous", "donor"]  # fmt: skip

    def get_donor(self, obj: Donation) -> str:
        return donor_label(obj, with_names=bool(self.context.get("with_names")))


class CashCollectionSerializer(serializers.ModelSerializer):
    fund = FundBriefSerializer()
    place = serializers.CharField(source="place.name", allow_null=True, default=None)
    entered_by = serializers.SerializerMethodField()
    validated_by = serializers.SerializerMethodField()

    class Meta:
        model = CashCollection
        fields = ["id", "fund", "place", "mass_date", "mass_label", "amount", "counter_one", "counter_two",
                  "observation", "status", "entered_by", "validated_by", "validated_at", "rejection_reason",
                  "deposit_id", "created_at"]  # fmt: skip

    def get_entered_by(self, obj: CashCollection) -> str:
        return _full_name(obj.entered_by)

    def get_validated_by(self, obj: CashCollection) -> str | None:
        return _full_name(obj.validated_by) if obj.validated_by else None


class ReconciliationIssueSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ISSUE_KINDS)
    reference = serializers.CharField()
    date = serializers.DateField()


class ReconciliationSerializer(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    online_charged = serializers.IntegerField()
    online_fees = serializers.IntegerField()
    online_net = serializers.IntegerField()
    cash = serializers.IntegerField()
    paid_out = serializers.IntegerField(help_text="Dons en ligne inclus dans un reversement (au diocèse, H1)")
    awaiting_payout = serializers.IntegerField()
    issues = ReconciliationIssueSerializer(many=True)


class ImpereeSerializer(serializers.ModelSerializer):
    raised = serializers.IntegerField(read_only=True)
    parishes_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Fund
        fields = ["id", "title", "description", "starts_on", "ends_on", "remit_by", "messe_anticipee_incluse", "status",
                  "authorization_ref",
                  "decided_by_office", "raised", "parishes_count", "created_at"]  # fmt: skip


class ImpereeFollowRowSerializer(serializers.Serializer):
    fund_id = serializers.UUIDField()
    parish_id = serializers.UUIDField()
    parish = serializers.CharField()
    status = serializers.CharField()
    online = serializers.IntegerField()
    cash = serializers.IntegerField()
    count = serializers.IntegerField()
    total = serializers.IntegerField()
    remitted_confirmed = serializers.IntegerField(help_text="Espèces remises, réception confirmée par la curie")
    remitted_declared = serializers.IntegerField(help_text="Remises déclarées, en attente de confirmation")
    to_remit = serializers.IntegerField(help_text="Espèces restant à remettre")
    remit_by = serializers.DateField(allow_null=True)


class CashDepositSerializer(serializers.ModelSerializer):
    collections_count = serializers.IntegerField(read_only=True)
    declared_by = serializers.SerializerMethodField()

    class Meta:
        model = CashDeposit
        fields = ["id", "node_id", "deposited_on", "bank_label", "slip_number", "amount", "note", "collections_count",
                  "declared_by", "created_at"]  # fmt: skip

    def get_declared_by(self, obj: CashDeposit) -> str:
        return _full_name(obj.declared_by)


class RemittanceSerializer(serializers.ModelSerializer):
    fund = FundBriefSerializer()
    parish = serializers.CharField(source="node.name")
    declared_by = serializers.SerializerMethodField()
    confirmed_by = serializers.SerializerMethodField()

    class Meta:
        model = CuriaRemittance
        fields = ["id", "fund", "node_id", "parish", "amount", "remitted_on", "mode", "reference", "status",
                  "declared_by", "confirmed_by", "confirmed_at", "rejection_reason", "created_at"]  # fmt: skip

    def get_declared_by(self, obj: CuriaRemittance) -> str:
        return _full_name(obj.declared_by)

    def get_confirmed_by(self, obj: CuriaRemittance) -> str | None:
        return _full_name(obj.confirmed_by) if obj.confirmed_by else None


class MonthClosingSerializer(serializers.ModelSerializer):
    closed_by = serializers.SerializerMethodField(help_text="Vide : clôture automatique")
    totals = serializers.DictField(help_text="Totaux figés : collecte, en_ligne, especes, affecte, par_type_fonds")

    class Meta:
        model = MonthClosing
        fields = ["id", "node_id", "month", "closed_by", "totals", "created_at"]

    def get_closed_by(self, obj: MonthClosing) -> str:
        return _full_name(obj.closed_by) if obj.closed_by else ""


class AdjustmentSerializer(serializers.ModelSerializer):
    fund = FundBriefSerializer()
    donation_reference = serializers.CharField(source="donation.reference", allow_null=True, default=None)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = DonationAdjustment
        fields = ["id", "fund", "kind", "channel", "amount", "net_amount", "value_date", "reason", "donation_reference",
                  "created_by", "created_at"]  # fmt: skip

    def get_created_by(self, obj: DonationAdjustment) -> str:
        return _full_name(obj.created_by) if obj.created_by else ""


class PaymentIncidentSerializer(serializers.ModelSerializer):
    reference = serializers.CharField(source="donation.reference")
    fund = FundBriefSerializer(source="donation.fund")
    amount = serializers.IntegerField(source="donation.charged_amount", help_text="Montant attendu (payé)")
    donation_status = serializers.CharField(source="donation.status")
    resolved_by = serializers.SerializerMethodField()

    class Meta:
        model = PaymentIncident
        fields = ["id", "kind", "status", "reference", "fund", "amount", "reported_amount", "donation_status",
                  "resolution", "note", "resolved_by", "resolved_at", "created_at"]  # fmt: skip

    def get_resolved_by(self, obj: PaymentIncident) -> str | None:
        return _full_name(obj.resolved_by) if obj.resolved_by else None


class PayoutSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ["id", "provider", "external_ref", "paid_at", "gross_amount", "fee_amount", "net_amount", "status",
                  "discrepancy_amount", "unmatched_count", "reconciled_at"]  # fmt: skip


class IncidentSerializer(serializers.Serializer):
    at = serializers.DateTimeField()
    provider = serializers.CharField()
    status = serializers.CharField()
    error = serializers.CharField()


class HealthSerializer(serializers.Serializer):
    provider = serializers.CharField()
    webhooks_24h = serializers.IntegerField()
    webhooks_failed_24h = serializers.IntegerField()
    webhooks_7d_by_status = serializers.DictField(child=serializers.IntegerField())
    last_webhook_at = serializers.DateTimeField(allow_null=True)
    pending_payments = serializers.IntegerField()
    oldest_pending_at = serializers.DateTimeField(allow_null=True)
    payouts_with_discrepancy = serializers.IntegerField()
    payouts_to_reconcile = serializers.IntegerField()
    incidents = IncidentSerializer(many=True)


class ActivationSerializer(serializers.ModelSerializer):
    node = NodeBriefSerializer()

    class Meta:
        model = DonationActivation
        fields = ["node", "enabled", "authorization_ref", "authorization_date", "authorization_text",
                  "allocation_key", "receipt_prefix", "updated_at"]  # fmt: skip
