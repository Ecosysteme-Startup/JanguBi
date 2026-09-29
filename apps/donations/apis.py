"""Dons et quêtes : couche HTTP uniquement (ADR-017 ; cadrage DONS-00 §7)."""

import datetime
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin, PermissionClassesType
from apps.api.pagination import LimitOffsetPagination, get_paginated_response, paginated_response_serializer
from apps.api.v1 import V1ApiMixin, error_body
from apps.authentication.keycloak import KeycloakJWTAuthentication
from apps.core.exceptions import ApplicationError, NotFoundError
from apps.donations import (
    access,
    exports,
    selectors,
    selectors_analyse,
    services,
    services_cloture,
    services_tresorerie,
)
from apps.donations.enums import DonationStatus
from apps.donations.providers import known_provider
from apps.donations.serializers import (
    ActivationInputSerializer,
    ActivationSerializer,
    AdjustmentInputSerializer,
    AdjustmentSerializer,
    CashCollectionFilterSerializer,
    CashCollectionInputSerializer,
    CashCollectionSerializer,
    CashDepositInputSerializer,
    CashDepositSerializer,
    CashRejectInputSerializer,
    CheckoutInputSerializer,
    CheckoutOutputSerializer,
    DonationStatusSerializer,
    DonorSummarySerializer,
    ExportQuerySerializer,
    FundCreateInputSerializer,
    FundListFilterSerializer,
    FundNewsInputSerializer,
    FundNewsSerializer,
    FundUpdateInputSerializer,
    HealthSerializer,
    ImpereeCreateInputSerializer,
    ImpereeFollowRowSerializer,
    ImpereeSerializer,
    IncidentFilterSerializer,
    IncidentResolveInputSerializer,
    MonthClosingInputSerializer,
    MonthClosingSerializer,
    MonthQuerySerializer,
    MyDonationSerializer,
    MyDonationsFilterSerializer,
    NodeQuerySerializer,
    OperationSerializer,
    OperationsFilterSerializer,
    ParishSummarySerializer,
    PaymentIncidentSerializer,
    PayoutSerializer,
    PeriodQuerySerializer,
    PublicFundDetailSerializer,
    PublicParishSerializer,
    ReconciliationSerializer,
    RefundInputSerializer,
    RemittanceFilterSerializer,
    RemittanceInputSerializer,
    RemittanceSerializer,
    StaffFundSerializer,
    YearQuerySerializer,
    amounts_payload,
    authorization_payload,
)
from apps.donations.serializers_analyse import (
    ActiviteQuerySerializer,
    ActiviteSerializer,
    AnalyseQuerySerializer,
    AnalyseSerializer,
)
from apps.hierarchy import selectors as hierarchy_selectors
from apps.hierarchy.authz import HasAnyCapability, HasCapability

TAG = ["dons"]
_PAGINATION = [
    OpenApiParameter("limit", int, description="Nombre de résultats (défaut 10, max 50)"),
    OpenApiParameter("offset", int, description="Décalage"),
]


class CheckoutRateThrottle(SimpleRateThrottle):
    """Checkout public : quota par adresse IP (``DONATIONS_CHECKOUT_THROTTLE_RATE``)."""

    scope = "dons_checkout"

    def get_rate(self) -> str | None:
        return settings.DONATIONS_CHECKOUT_THROTTLE_RATE

    def get_cache_key(self, request: Any, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class _PublicApi(V1ApiMixin, APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)


class _AuthedApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (IsAuthenticated,)


def _parish(node_id: Any) -> Any:
    node = hierarchy_selectors.node_get(node_id=node_id)
    if not access.is_parish(node):
        raise ApplicationError("Ce nœud n'est pas une paroisse.", code="not_a_parish")
    return node


def _place_or_none(place_id: Any) -> Any:
    return hierarchy_selectors.place_get(place_id=place_id) if place_id else None


def _query(serializer_class: Any, request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def _body(serializer_class: Any, request: Request) -> dict[str, Any]:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


# --- Public ---------------------------------------------------------------------------------


class PublicParishApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="public_dons_parish",
        summary="Page de don d'une paroisse : activation, mention d'autorisation, montants, fonds ouverts",
        responses=PublicParishSerializer,
    )
    def get(self, request: Request, node_id: str) -> Response:
        node = _parish(node_id)
        activation = selectors.activation_for(node=node)
        funds = list(selectors.funds_open_for_parish(node=node)) if activation else []
        data = {
            "parish": node,
            "enabled": activation is not None,
            "authorization": authorization_payload(activation),
            **amounts_payload(),
            "funds": funds,
        }
        return Response(PublicParishSerializer(data).data)


class PublicFundApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="public_dons_fund",
        summary="Détail d'un fonds ou d'une campagne (montant réuni, nouvelles)",
        responses=PublicFundDetailSerializer,
    )
    def get(self, request: Request, fund_id: str) -> Response:
        return Response(PublicFundDetailSerializer(selectors.fund_public_get(fund_id=fund_id)).data)


class CheckoutApi(V1ApiMixin, APIView):
    """Compte facultatif : un jeton valide rattache le don au fidèle ; sans jeton, don sans compte."""

    authentication_classes = (KeycloakJWTAuthentication,)
    permission_classes = (AllowAny,)
    throttle_classes = (CheckoutRateThrottle,)

    @extend_schema(
        tags=TAG,
        operation_id="dons_checkout_create",
        summary="Préparer un don et obtenir l'URL de paiement de l'agrégateur",
        parameters=[
            OpenApiParameter(
                "Idempotency-Key", str, OpenApiParameter.HEADER, required=False,
                description="Même clé = même don (double clic, reprise réseau)",
            )  # fmt: skip
        ],
        request=CheckoutInputSerializer,
        responses={
            201: CheckoutOutputSerializer,
            200: CheckoutOutputSerializer,
            429: OpenApiResponse(description="Trop de demandes depuis cette adresse"),
            503: OpenApiResponse(description="Agrégateur indisponible"),
        },
    )
    def post(self, request: Request) -> Response:
        data = _body(CheckoutInputSerializer, request)
        fund = selectors.fund_public_get(fund_id=data["fund_id"])
        key = (request.headers.get("Idempotency-Key") or "")[:80]
        donation, attempt, created = services.checkout_create(
            fund=fund,
            amount=data["amount"],
            fees_covered=data["fees_covered"],
            anonymous=data["anonymous"],
            donor=request.user,
            donor_email=data["email"],
            idempotency_key=key,
            source=data["source"],
            place=_place_or_none(data.get("place_id")),
        )
        payload = CheckoutOutputSerializer({"donation": donation, "attempt": attempt}).data
        return Response(payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class CheckoutStatusApi(_PublicApi):
    @extend_schema(
        tags=TAG,
        operation_id="dons_checkout_status",
        summary="Statut d'un don après le retour de la page de paiement (affichage seulement)",
        responses=DonationStatusSerializer,
    )
    def get(self, request: Request, donation_id: str) -> Response:
        donation = services.donation_mark_returned(donation=selectors.donation_public_get(donation_id=donation_id))
        return Response(DonationStatusSerializer(donation).data)


class WebhookApi(APIView):
    """Notification de l'agrégateur (IPN). Réponse immédiate ; traitement en tâche."""

    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(
        tags=TAG,
        operation_id="dons_webhook",
        summary="Notification signée de l'agrégateur",
        request=OpenApiTypes.BINARY,
        responses={200: OpenApiResponse(description="Reçue"), 400: OpenApiResponse(description="Signature invalide")},
    )
    def post(self, request: Request, provider: str) -> Response:
        if not known_provider(provider) or provider != settings.DONATIONS_PROVIDER:
            return Response(error_body(code="not_found", message="Agrégateur inconnu."), status=404)
        event, _ = services.webhook_receive(provider_code=provider, headers=dict(request.headers), body=request.body)
        if not event.signature_valid:
            return Response(error_body(code="invalid_signature", message="Signature invalide."), status=400)
        return Response({"received": True})


# --- Fidèle ---------------------------------------------------------------------------------


class MyDonationsApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="me_dons_list",
        summary="Mes dons (filtres par fonds et par année)",
        parameters=[MyDonationsFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(MyDonationSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = _query(MyDonationsFilterSerializer, request)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=MyDonationSerializer,
            queryset=selectors.donations_for_donor(user=request.user, fund_id=filters.get("fund"),
                                                   year=filters.get("year")),  # fmt: skip
            request=request,
            view=self,
        )


class MySummaryApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="me_dons_summary",
        summary="Total de mes dons sur l'année (visible de moi seul)",
        parameters=[YearQuerySerializer],
        responses=DonorSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        year = _query(YearQuerySerializer, request).get("year") or timezone.localdate().year
        return Response(DonorSummarySerializer(selectors.donor_summary(user=request.user, year=year)).data)


class MyReceiptApi(_AuthedApi):
    @extend_schema(
        tags=TAG,
        operation_id="me_dons_receipt",
        summary="Reçu simple d'un don confirmé (PDF, pas un reçu fiscal)",
        responses={(200, "application/pdf"): OpenApiTypes.BINARY},
    )
    def get(self, request: Request, donation_id: str) -> HttpResponse:
        donation = selectors.donation_get_for_donor(user=request.user, donation_id=donation_id)
        if donation.status != DonationStatus.CONFIRME:
            raise NotFoundError("Le reçu n'est disponible que pour un don confirmé.", code="receipt_unavailable")
        response = HttpResponse(exports.receipt_pdf(donation), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="recu-{donation.reference}.pdf"'
        return response


# --- Paroisse -------------------------------------------------------------------------------


class _StaffApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes: PermissionClassesType = (
        IsAuthenticated,
        HasAnyCapability("dons.voir_fonds", "dons.gerer_fonds", "dons.saisir_quete"),
    )


class FundListCreateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_funds_list",
        summary="Fonds d'une paroisse (avec montants réunis)",
        parameters=[FundListFilterSerializer],
        responses=StaffFundSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        filters = _query(FundListFilterSerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        funds = selectors.funds_for_parish(node=node, status=filters.get("status"), kind=filters.get("kind"))
        return Response(StaffFundSerializer(funds, many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_funds_create",
        summary="Créer un fonds ou une campagne (brouillon)",
        request=FundCreateInputSerializer,
        responses={201: StaffFundSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(FundCreateInputSerializer, request)
        node = _parish(data.pop("node"))
        image = selectors.image_get(file_id=data.pop("image_id"), user=request.user)
        place = _place_or_none(data.pop("place_id"))
        fund = services.fund_create(actor=request.user, node=node, image=image, place=place, **data)
        return Response(StaffFundSerializer(selectors.fund_get(fund_id=fund.pk)).data, status=status.HTTP_201_CREATED)


class FundDetailApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_funds_detail", summary="Détail d'un fonds",
                   responses=StaffFundSerializer)  # fmt: skip
    def get(self, request: Request, fund_id: str) -> Response:
        fund = selectors.fund_get(fund_id=fund_id)
        access.require_parish_level(request.user, "dons.voir_fonds", fund.node)
        return Response(StaffFundSerializer(fund).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_funds_update",
        summary="Modifier un fonds (titre, usage, dates, objectif, visuel)",
        request=FundUpdateInputSerializer,
        responses=StaffFundSerializer,
    )
    def patch(self, request: Request, fund_id: str) -> Response:
        fund = selectors.fund_get(fund_id=fund_id)
        data = _body(FundUpdateInputSerializer, request)
        if "image_id" in data:
            data["image"] = selectors.image_get(file_id=data.pop("image_id"), user=request.user)
        if "place_id" in data:
            data["place"] = _place_or_none(data.pop("place_id"))
        services.fund_update(fund=fund, actor=request.user, **data)
        return Response(StaffFundSerializer(selectors.fund_get(fund_id=fund_id)).data)


class FundPublishApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_funds_publish", summary="Publier (brouillon → ouvert)",
                   request=None, responses=StaffFundSerializer)  # fmt: skip
    def post(self, request: Request, fund_id: str) -> Response:
        services.fund_publish(fund=selectors.fund_get(fund_id=fund_id), actor=request.user)
        return Response(StaffFundSerializer(selectors.fund_get(fund_id=fund_id)).data)


class FundCloseApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_funds_close", summary="Clore (ouvert → clos)",
                   request=None, responses=StaffFundSerializer)  # fmt: skip
    def post(self, request: Request, fund_id: str) -> Response:
        services.fund_close(fund=selectors.fund_get(fund_id=fund_id), actor=request.user)
        return Response(StaffFundSerializer(selectors.fund_get(fund_id=fund_id)).data)


class FundNewsApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_funds_news", summary="Publier une nouvelle de campagne",
                   request=FundNewsInputSerializer, responses={201: FundNewsSerializer})  # fmt: skip
    def post(self, request: Request, fund_id: str) -> Response:
        data = _body(FundNewsInputSerializer, request)
        update = services.fund_news_post(fund=selectors.fund_get(fund_id=fund_id), actor=request.user, **data)
        return Response(FundNewsSerializer(update).data, status=status.HTTP_201_CREATED)


class SummaryApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_summary",
        summary="Synthèse du mois : par fonds, par moyen, en ligne ou espèces, série quotidienne",
        parameters=[MonthQuerySerializer],
        responses=ParishSummarySerializer,
    )
    def get(self, request: Request) -> Response:
        filters = _query(MonthQuerySerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        month = (
            datetime.date.fromisoformat(f"{filters['month']}-01") if filters.get("month") else timezone.localdate()
        )
        return Response(ParishSummarySerializer(selectors.parish_summary(node=node, month=month)).data)


class OperationsApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_operations",
        summary="Opérations (noms masqués sans dons.voir_donateurs ; un don anonyme reste anonyme)",
        parameters=[OperationsFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(OperationSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = _query(OperationsFilterSerializer, request)
        node = _parish(filters.pop("node"))
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        queryset = selectors.operations_for_parish(node=node, fund_id=filters.pop("fund", None), **filters)
        paginator = LimitOffsetPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        context = {"with_names": access.parish_level(request.user, "dons.voir_donateurs", node)}
        return paginator.get_paginated_response(OperationSerializer(page, many=True, context=context).data)


class RefundApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_refund",
        summary="Constater le remboursement d'un don (fait chez l'agrégateur)",
        request=RefundInputSerializer,
        responses=OperationSerializer,
    )
    def post(self, request: Request, donation_id: str) -> Response:
        data = _body(RefundInputSerializer, request)
        donation = services.donation_refund(
            donation=selectors.operation_get(donation_id=donation_id), actor=request.user, note=data["note"]
        )
        with_names = access.parish_level(request.user, "dons.voir_donateurs", donation.fund.node)
        return Response(OperationSerializer(selectors.operation_get(donation_id=donation.pk),
                                            context={"with_names": with_names}).data)  # fmt: skip


class CashCollectionListCreateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_cash_list",
        summary="Saisies de quêtes en espèces d'une paroisse",
        parameters=[CashCollectionFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(CashCollectionSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = _query(CashCollectionFilterSerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.saisir_quete", node)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=CashCollectionSerializer,
            queryset=selectors.cash_collections_for_parish(node=node, status=filters.get("status")),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_cash_create",
        summary="Saisir la quête en espèces d'une messe (deux compteurs)",
        request=CashCollectionInputSerializer,
        responses={201: CashCollectionSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(CashCollectionInputSerializer, request)
        node = _parish(data.pop("node"))
        fund = selectors.fund_get(fund_id=data.pop("fund_id"))
        place = _place_or_none(data.pop("place_id"))
        collection = services.cash_collection_create(actor=request.user, node=node, fund=fund, place=place, **data)
        return Response(CashCollectionSerializer(collection).data, status=status.HTTP_201_CREATED)


class CashCollectionValidateApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_cash_validate",
                   summary="Valider une saisie (par une autre personne)", request=None,
                   responses=CashCollectionSerializer)  # fmt: skip
    def post(self, request: Request, collection_id: int) -> Response:
        collection = services.cash_collection_validate(
            collection=selectors.cash_collection_get(collection_id=collection_id), actor=request.user
        )
        return Response(CashCollectionSerializer(selectors.cash_collection_get(collection_id=collection.pk)).data)


class CashCollectionRejectApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_cash_reject", summary="Rejeter une saisie (motif)",
                   request=CashRejectInputSerializer, responses=CashCollectionSerializer)  # fmt: skip
    def post(self, request: Request, collection_id: int) -> Response:
        data = _body(CashRejectInputSerializer, request)
        collection = services.cash_collection_reject(
            collection=selectors.cash_collection_get(collection_id=collection_id), actor=request.user, **data
        )
        return Response(CashCollectionSerializer(selectors.cash_collection_get(collection_id=collection.pk)).data)


class CashDepositListCreateApi(_StaffApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_deposits_list",
        summary="Dépôts en banque des espèces d'une paroisse",
        parameters=[NodeQuerySerializer, *_PAGINATION],
        responses=paginated_response_serializer(CashDepositSerializer),
    )
    def get(self, request: Request) -> Response:
        node = _parish(_query(NodeQuerySerializer, request)["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=CashDepositSerializer,
            queryset=selectors.cash_deposits_for_parish(node=node),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_deposits_create",
        summary="Déclarer le dépôt en banque de quêtes validées (montant = somme des quêtes)",
        request=CashDepositInputSerializer,
        responses={201: CashDepositSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(CashDepositInputSerializer, request)
        node = _parish(data.pop("node"))
        deposit = services_tresorerie.cash_deposit_declare(actor=request.user, node=node, **data)
        return Response(
            CashDepositSerializer(selectors.cash_deposit_get(deposit_id=deposit.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class RemittanceListCreateApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (
        IsAuthenticated,
        HasAnyCapability("dons.voir_fonds", "dons.gerer_fonds", "dons.definir_quete_imperee"),
    )

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_remittances_list",
        summary="Remises à la curie des espèces de quête impérée (d'une paroisse, ou de tout le diocèse)",
        parameters=[RemittanceFilterSerializer, *_PAGINATION],
        responses=paginated_response_serializer(RemittanceSerializer),
    )
    def get(self, request: Request) -> Response:
        filters = _query(RemittanceFilterSerializer, request)
        node = hierarchy_selectors.node_get(node_id=filters["node"])
        if access.is_diocese(node):
            access.require_diocese(request.user, "dons.definir_quete_imperee", node)
        else:
            access.require_parish_level(request.user, "dons.voir_fonds", node)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=RemittanceSerializer,
            queryset=selectors.remittances_for(node=node, status=filters.get("status")),
            request=request,
            view=self,
        )

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_remittances_create",
        summary="Déclarer une remise à la curie (espèces d'une quête impérée)",
        request=RemittanceInputSerializer,
        responses={201: RemittanceSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(RemittanceInputSerializer, request)
        fund = selectors.fund_get(fund_id=data.pop("fund_id"))
        remittance = services_tresorerie.curia_remittance_declare(actor=request.user, fund=fund, **data)
        return Response(
            RemittanceSerializer(selectors.remittance_get(remittance_id=remittance.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class RemittanceConfirmApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("dons.definir_quete_imperee"))

    @extend_schema(tags=TAG, operation_id="staff_dons_remittances_confirm",
                   summary="Confirmer la réception d'une remise (curie, autre personne que la déclaration)",
                   request=None, responses=RemittanceSerializer)  # fmt: skip
    def post(self, request: Request, remittance_id: int) -> Response:
        remittance = services_tresorerie.curia_remittance_confirm(
            remittance=selectors.remittance_get(remittance_id=remittance_id), actor=request.user
        )
        return Response(RemittanceSerializer(selectors.remittance_get(remittance_id=remittance.pk)).data)


class RemittanceContestApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("dons.definir_quete_imperee"))

    @extend_schema(tags=TAG, operation_id="staff_dons_remittances_contest",
                   summary="Contester une remise (motif obligatoire)", request=CashRejectInputSerializer,
                   responses=RemittanceSerializer)  # fmt: skip
    def post(self, request: Request, remittance_id: int) -> Response:
        data = _body(CashRejectInputSerializer, request)
        remittance = services_tresorerie.curia_remittance_contest(
            remittance=selectors.remittance_get(remittance_id=remittance_id), actor=request.user, **data
        )
        return Response(RemittanceSerializer(selectors.remittance_get(remittance_id=remittance.pk)).data)


class AnalysisApi(V1ApiMixin, ApiAuthMixin, APIView):
    """Tableaux de bord : paroisse (nomination locale, exact) ou diocèse / doyenné (agrégats arrondis)."""

    permission_classes = (IsAuthenticated, HasAnyCapability("dons.voir_fonds", "dons.voir_agregats"))

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_analysis",
        summary="Analyse des dons : synthèse, tendance, à traiter (contrat : docs/API-DONS-ANALYSE.md)",
        description=(
            "niveau=paroisse : `dons.voir_fonds` par une nomination sur la paroisse même, montants exacts. "
            "niveau=diocese : `dons.voir_agregats` sur le diocèse ou le doyenné, montants arrondis au millier. "
            "Aucun nom de donateur ; paroisses en ordre alphabétique ; aucun tri par montant ; « à traiter » "
            "trié par échéance croissante."
        ),
        parameters=[AnalyseQuerySerializer],
        responses=AnalyseSerializer,
    )
    def get(self, request: Request) -> Response:
        filters = _query(AnalyseQuerySerializer, request)
        node = hierarchy_selectors.node_get(node_id=filters["noeud"])
        level = filters["niveau"]
        if level == "paroisse":
            access.require_parish_level(request.user, "dons.voir_fonds", node)
        else:
            access.require_aggregates(request.user, node)
            if filters["periode"] == "semaine":
                raise ApplicationError(
                    "Au-dessus de la paroisse, la période minimale est le mois.", code="period_not_allowed"
                )
        period = selectors_analyse.period_parse(filters["periode"], filters["date"] or None)
        data = selectors_analyse.donations_analysis(node=node, level=level, period=period)
        return Response(AnalyseSerializer(data).data)


class MonthClosingApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_closings_list", summary="Mois clos d'une paroisse",
                   parameters=[NodeQuerySerializer], responses=MonthClosingSerializer(many=True))  # fmt: skip
    def get(self, request: Request) -> Response:
        node = _parish(_query(NodeQuerySerializer, request)["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        return Response(MonthClosingSerializer(selectors.closings_for_parish(node=node), many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_closings_create",
        summary="Clore un mois écoulé (totaux figés ; plus aucune quête ne s'y saisit)",
        request=MonthClosingInputSerializer,
        responses={201: MonthClosingSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(MonthClosingInputSerializer, request)
        node = _parish(data["node"])
        month = datetime.date.fromisoformat(f"{data['month']}-01")
        closing = services_cloture.month_close(node=node, month=month, actor=request.user)
        return Response(MonthClosingSerializer(closing).data, status=status.HTTP_201_CREATED)


class AdjustmentApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_adjustments_list",
                   summary="Écritures d'ajustement (remboursements, corrections de mois clos)",
                   parameters=[NodeQuerySerializer, *_PAGINATION],
                   responses=paginated_response_serializer(AdjustmentSerializer))  # fmt: skip
    def get(self, request: Request) -> Response:
        node = _parish(_query(NodeQuerySerializer, request)["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=AdjustmentSerializer,
            queryset=selectors.adjustments_for_parish(node=node),
            request=request,
            view=self,
        )

    @extend_schema(tags=TAG, operation_id="staff_dons_adjustments_create",
                   summary="Passer une écriture de correction (datée du jour, motif obligatoire)",
                   request=AdjustmentInputSerializer, responses={201: AdjustmentSerializer})  # fmt: skip
    def post(self, request: Request) -> Response:
        data = _body(AdjustmentInputSerializer, request)
        fund = selectors.fund_get(fund_id=data.pop("fund_id"))
        adjustment = services_cloture.adjustment_create(actor=request.user, fund=fund, **data)
        return Response(AdjustmentSerializer(adjustment).data, status=status.HTTP_201_CREATED)


class IncidentListApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_incidents_list",
                   summary="Incidents de paiement (paiements tardifs, montants incohérents) d'une paroisse",
                   parameters=[IncidentFilterSerializer], responses=PaymentIncidentSerializer(many=True))  # fmt: skip
    def get(self, request: Request) -> Response:
        filters = _query(IncidentFilterSerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.voir_fonds", node)
        incidents = selectors.incidents_for_parish(node=node, status=filters.get("status"))
        return Response(PaymentIncidentSerializer(incidents, many=True).data)


class IncidentResolveApi(_StaffApi):
    @extend_schema(tags=TAG, operation_id="staff_dons_incidents_resolve",
                   summary="Régulariser un incident (intégrer le paiement tardif, remboursé, sans suite)",
                   request=IncidentResolveInputSerializer, responses=PaymentIncidentSerializer)  # fmt: skip
    def post(self, request: Request, incident_id: int) -> Response:
        data = _body(IncidentResolveInputSerializer, request)
        incident = services_cloture.incident_resolve(
            incident=selectors.incident_get(incident_id=incident_id), actor=request.user, **data
        )
        return Response(PaymentIncidentSerializer(selectors.incident_get(incident_id=incident.pk)).data)


class ExportApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("dons.exporter"))

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_export",
        summary="Export comptable (CSV ou Excel)",
        parameters=[ExportQuerySerializer],
        responses={
            (200, "text/csv"): OpenApiTypes.STR,
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
        },
    )
    def get(self, request: Request) -> HttpResponse:
        filters = _query(ExportQuerySerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.exporter", node)
        rows = selectors.export_rows(
            node=node,
            date_from=filters["date_from"],
            date_to=filters["date_to"],
            fund_id=filters.get("fund"),
            with_names=access.parish_level(request.user, "dons.voir_donateurs", node),
        )
        services.export_logged(actor=request.user, node=node, rows=len(rows), fmt=filters["fichier"])
        name = f"dons-{filters['date_from']:%Y%m%d}-{filters['date_to']:%Y%m%d}"
        if filters["fichier"] == "xlsx":
            response = HttpResponse(
                exports.export_xlsx(rows),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
            return response
        response = HttpResponse(exports.export_csv(rows), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{name}.csv"'
        return response


class ReconciliationApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("dons.exporter"))

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_reconciliation",
        summary="Rapprochement de la paroisse sur une période (écarts signalés)",
        parameters=[PeriodQuerySerializer],
        responses=ReconciliationSerializer,
    )
    def get(self, request: Request) -> Response:
        filters = _query(PeriodQuerySerializer, request)
        node = _parish(filters["node"])
        access.require_parish_level(request.user, "dons.exporter", node)
        data = selectors.parish_reconciliation(node=node, date_from=filters["date_from"], date_to=filters["date_to"])
        return Response(ReconciliationSerializer(data).data)


# --- Diocèse --------------------------------------------------------------------------------


class _DioceseApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("dons.definir_quete_imperee"))


def _diocese(node_id: Any) -> Any:
    node = hierarchy_selectors.node_get(node_id=node_id)
    if not access.is_diocese(node):
        raise ApplicationError("Ce nœud n'est pas un diocèse.", code="not_a_diocese")
    return node


class ImpereeListCreateApi(_DioceseApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_imperees_list",
        summary="Quêtes impérées d'un diocèse (agrégats)",
        parameters=[NodeQuerySerializer],
        responses=ImpereeSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        diocese = _diocese(_query(NodeQuerySerializer, request)["node"])
        access.require_diocese(request.user, "dons.definir_quete_imperee", diocese)
        return Response(ImpereeSerializer(selectors.imperees_for_diocese(diocese=diocese), many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_imperees_create",
        summary="Définir une quête impérée (déclinée par paroisse, reversée à la curie)",
        request=ImpereeCreateInputSerializer,
        responses={201: ImpereeSerializer},
    )
    def post(self, request: Request) -> Response:
        data = _body(ImpereeCreateInputSerializer, request)
        diocese = _diocese(data.pop("node"))
        parish_ids = data.pop("parish_ids")
        parishes = [hierarchy_selectors.node_get(node_id=pk) for pk in parish_ids] if parish_ids else None
        fund = services.imperee_create(actor=request.user, diocese=diocese, parishes=parishes, **data)
        created = selectors.imperees_for_diocese(diocese=diocese).get(pk=fund.pk)
        return Response(ImpereeSerializer(created).data, status=status.HTTP_201_CREATED)


class ImpereeFollowApi(_DioceseApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_imperees_follow",
        summary="Suivi d'une quête impérée par paroisse (sommes, aucun nom)",
        responses=ImpereeFollowRowSerializer(many=True),
    )
    def get(self, request: Request, fund_id: str) -> Response:
        fund = selectors.imperee_get(fund_id=fund_id)
        access.require_diocese(request.user, "dons.definir_quete_imperee", fund.node)
        return Response(ImpereeFollowRowSerializer(selectors.imperee_follow(fund=fund), many=True).data)


class PayoutListApi(_DioceseApi):
    @extend_schema(
        tags=TAG,
        operation_id="staff_dons_payouts",
        summary="Reversements de l'agrégateur reçus par le diocèse (H1)",
        parameters=[NodeQuerySerializer, *_PAGINATION],
        responses=paginated_response_serializer(PayoutSerializer),
    )
    def get(self, request: Request) -> Response:
        diocese = _diocese(_query(NodeQuerySerializer, request)["node"])
        access.require_diocese(request.user, "dons.definir_quete_imperee", diocese)
        return get_paginated_response(
            pagination_class=LimitOffsetPagination,
            serializer_class=PayoutSerializer,
            queryset=selectors.payouts_for_diocese(diocese=diocese),
            request=request,
            view=self,
        )


# --- Plateforme -----------------------------------------------------------------------------


class _PlatformApi(V1ApiMixin, ApiAuthMixin, APIView):
    permission_classes = (IsAuthenticated, HasCapability("plateforme.admin"))


class HealthApi(_PlatformApi):
    @extend_schema(
        tags=TAG,
        operation_id="platform_dons_health",
        summary="Santé de l'intégration de paiement (webhooks, attentes, rapprochement, incidents)",
        responses=HealthSerializer,
    )
    def get(self, request: Request) -> Response:
        return Response(HealthSerializer(selectors.platform_health()).data)


class ActivityApi(_PlatformApi):
    @extend_schema(
        tags=TAG,
        operation_id="platform_dons_activity",
        summary="Activité des paiements : nombres, taux, délais, incidents — aucun montant (docs/API-DONS-ANALYSE.md)",
        parameters=[ActiviteQuerySerializer],
        responses=ActiviteSerializer,
    )
    def get(self, request: Request) -> Response:
        filters = _query(ActiviteQuerySerializer, request)
        period = selectors_analyse.period_parse(filters["periode"], filters["date"] or None)
        return Response(ActiviteSerializer(selectors_analyse.platform_activity(period=period)).data)


class ActivationApi(_PlatformApi):
    @extend_schema(tags=TAG, operation_id="platform_dons_activations_list",
                   summary="Paroisses et état de leur collecte", responses=ActivationSerializer(many=True))  # fmt: skip
    def get(self, request: Request) -> Response:
        return Response(ActivationSerializer(selectors.activations_list(), many=True).data)

    @extend_schema(
        tags=TAG,
        operation_id="platform_dons_activations_set",
        summary="Ouvrir ou fermer la collecte d'une paroisse (autorisation écrite requise)",
        request=ActivationInputSerializer,
        responses=ActivationSerializer,
    )
    def put(self, request: Request) -> Response:
        data = _body(ActivationInputSerializer, request)
        node = _parish(data.pop("node"))
        activation = services.activation_set(actor=request.user, node=node, **data)
        return Response(ActivationSerializer(activation).data)
