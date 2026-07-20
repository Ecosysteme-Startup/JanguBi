"""
APIs de gestion des utilisateurs.

Endpoints publics :
  POST /api/users/register/                   Inscription fidèle
  POST /api/users/verify-email/               Activation du compte (token URL)
  POST /api/users/password/reset/request/     Demande de réinitialisation MDP
  POST /api/users/password/reset/confirm/     Confirmation réinitialisation MDP
  POST /api/users/email/change/revert/        Réversion changement email (sans auth)

Endpoints authentifiés (propriétaire) :
  GET  /api/users/me/                         Mon profil complet
  PATCH /api/users/me/                        Mise à jour mon profil
  POST /api/users/password/change/            Changer mon mot de passe
  POST /api/users/email/change/request/       Demander un changement d'email
  POST /api/users/email/change/confirm/       Confirmer le changement (OTP)
  DELETE /api/users/me/                       Supprimer mon compte (soft)

Endpoints admin :
  GET  /api/users/                            Liste des utilisateurs
  GET  /api/users/{id}/                       Détail d'un utilisateur
  POST /api/users/admin/create/               Créer un compte admin (super_admin only)
  PATCH /api/users/{id}/toggle-active/        Activer / désactiver
  DELETE /api/users/{id}/                     Suppression soft
  DELETE /api/users/{id}/hard/                Suppression définitive

Chaîne de validation des comptes clergé → ``apis_clergy.py``.
Affectations de rôle scopées → ``apis_roles.py``.
Appartenances ecclésiales → ``apis_memberships.py``.
"""

from django.http import Http404
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.api.mixins import ApiAuthMixin
from apps.api.pagination import LimitOffsetPagination, get_paginated_response
from apps.api.serializers import ErrorResponseSerializer
from apps.core.exceptions import (
    ApplicationError,
    OtpExpiredError,
    OtpInvalidError,
    OtpLockedError,
    OtpRateLimitError,
    TokenExpiredError,
    TokenInvalidError,
)
from apps.users.enums import UserRole
from apps.users.permissions import IsAdminUser, IsDioceseAdminOrAbove, IsStaffOrAdminUser
from apps.users.selectors import (
    audit_log_list,
    user_get,
    user_get_login_data,
    user_get_with_profile,
    user_list,
)
from apps.users.serializers import MeOutputSerializer, MeUpdateInputSerializer
from apps.users.services import (
    email_change_confirm,
    email_change_request,
    email_change_revert,
    password_change,
    password_reset_confirm,
    password_reset_request,
    user_activate_account,
    user_create_by_admin,
    user_hard_delete,
    user_register_fidele,
    user_soft_delete,
    user_toggle_active,
    user_update_profile,
    verification_email_resend,
)


def _get_ip(request) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _handle_otp_error(exc: Exception) -> Response:
    """Convertit les exceptions OTP en réponses HTTP cohérentes."""
    if isinstance(exc, OtpLockedError):
        return Response({"detail": exc.message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if isinstance(exc, OtpRateLimitError):
        return Response({"detail": exc.message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    if isinstance(exc, (OtpExpiredError, OtpInvalidError)):
        # Message générique volontairement — ne révèle pas si c'est expiré ou faux
        return Response(
            {"detail": "Code incorrect ou expiré."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class UserListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    email = serializers.EmailField()
    phone_number = serializers.CharField()
    role = serializers.CharField()
    # Identité pastorale (dimension orthogonale au rôle admin) : permet à la liste
    # admin d'afficher « Prêtre/Évêque » pour le clergé (dont role reste 'fidele').
    pastoral_role = serializers.CharField(allow_null=True, allow_blank=True)
    is_active = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    is_admin = serializers.BooleanField()
    date_joined = serializers.SerializerMethodField()
    user_profile = serializers.SerializerMethodField()

    def get_date_joined(self, obj):
        return obj.created_at.isoformat() if obj.created_at else None

    def get_user_profile(self, obj):
        p = getattr(obj, "profile", None)
        if not p:
            return None
        return {
            "first_name": p.first_name,
            "last_name": p.last_name,
            "title": p.title,
            "phone": str(p.phone) if p.phone else None,
            # FK Parish → {id, name} (objet brut = non sérialisable JSON, BUG-B1).
            "primary_parish": (
                {"id": p.primary_parish_id, "name": p.primary_parish.name}
                if p.primary_parish_id
                else None
            ),
            "avatar": p.avatar.url if p.avatar else None,
        }


class UserListPaginatedResponseSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = UserListItemSerializer(many=True)


# ===========================================================================
# INSCRIPTION
# ===========================================================================

@extend_schema(tags=["Authentification"])
class FideleRegisterApi(APIView):
    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()
        phone_number = serializers.CharField(max_length=20)
        password = serializers.CharField(min_length=8, write_only=True)
        first_name = serializers.CharField(max_length=50)
        last_name = serializers.CharField(max_length=50)
        title = serializers.ChoiceField(choices=["MR", "MRS"])

    @extend_schema(
        summary="Inscription fidèle",
        description=(
            "Crée un compte fidèle (auto-inscription publique). "
            "Le compte est inactif jusqu'à la vérification de l'email. "
            "Un email de vérification est envoyé immédiatement."
        ),
        request=InputSerializer,
        responses={
            201: OpenApiResponse(description="Compte créé, email de vérification envoyé"),
            400: OpenApiResponse(description="Données invalides ou email déjà utilisé"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user_register_fidele(**s.validated_data, ip=_get_ip(request))
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {"detail": "Compte créé. Vérifiez votre email pour activer votre compte."},
            status=status.HTTP_201_CREATED,
        )


# ===========================================================================
# ACTIVATION DE COMPTE
# ===========================================================================

class EmailVerifyApi(APIView):
    class InputSerializer(serializers.Serializer):
        token = serializers.CharField()

    @extend_schema(
        tags=["Authentification"],
        summary="Activer le compte via le lien email",
        description=(
            "Valide le token reçu par email et active le compte. "
            "Le token est à usage unique (anti-replay) et expire après 24h."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="Compte activé avec succès"),
            400: OpenApiResponse(description="Token invalide ou expiré"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user_activate_account(token=s.validated_data["token"], ip=_get_ip(request))
        except (TokenInvalidError, TokenExpiredError) as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Votre compte est activé. Vous pouvez vous connecter."})


class EmailVerifyResendApi(APIView):
    """Renvoi du lien d'activation.

    Sans cet endpoint, un compte dont le lien a expiré (24 h) était définitivement
    bloqué : la réinscription est refusée et le compte reste `is_active=False`.
    """

    throttle_scope = "login"
    throttle_classes = [ScopedRateThrottle]

    class ResendInputSerializer(serializers.Serializer):
        email = serializers.EmailField()

    @extend_schema(
        tags=["Authentification"],
        summary="Renvoyer le lien d'activation du compte",
        description=(
            "Renvoie l'email de vérification à un compte encore inactif. "
            "**Paramètres d'entrée (JSON Body)** : `email`. "
            "La réponse est identique que le compte existe, soit déjà vérifié ou "
            "non (anti-énumération)."
        ),
        request=ResendInputSerializer,
        responses={
            200: OpenApiResponse(description="Demande prise en compte"),
            429: OpenApiResponse(description="Trop de demandes"),
        },
    )
    def post(self, request):
        s = self.ResendInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            verification_email_resend(email=s.validated_data["email"], ip=_get_ip(request))
        except OtpRateLimitError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Message volontairement neutre : il ne doit jamais révéler si l'adresse
        # correspond à un compte, ni si ce compte est déjà activé.
        return Response(
            {
                "detail": (
                    "Si un compte non activé correspond à cette adresse, "
                    "un nouvel email de vérification vient d'être envoyé."
                )
            }
        )


# ===========================================================================
# MOT DE PASSE
# ===========================================================================

class PasswordResetRequestApi(APIView):
    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()

    @extend_schema(
        tags=["Authentification"],
        summary="Demande de réinitialisation de mot de passe",
        description=(
            "Initie la procédure de récupération de compte. "
            "**Paramètres d'entrée (JSON Body)** : `email`. "
            "Envoie un lien de réinitialisation si l'email est enregistré. "
            "La réponse est identique que l'email existe ou non (anti-énumération) "
            "et inclut un délai factice pour prévenir les Timing Attacks."
        ),
        request=InputSerializer,
        responses={200: OpenApiResponse(description="Email envoyé si l'adresse est connue")},
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            password_reset_request(email=s.validated_data["email"], ip=_get_ip(request))
        except OtpRateLimitError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        # Réponse uniforme — ne révèle pas si l'email existe
        return Response({
            "detail": "Si cette adresse est enregistrée, vous recevrez un email sous peu."
        })


class PasswordResetConfirmApi(APIView):
    class InputSerializer(serializers.Serializer):
        token = serializers.CharField()
        new_password = serializers.CharField(min_length=8, write_only=True)

    @extend_schema(
        tags=["Authentification"],
        summary="Confirmation de la réinitialisation",
        description=(
            "Applique le nouveau mot de passe. "
            "**Paramètres d'entrée (JSON Body)** : `token`, `new_password`. "
            "Le token est à usage unique et expire après 20 minutes."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="Mot de passe réinitialisé"),
            400: OpenApiResponse(description="Token invalide / expiré ou mot de passe trop faible"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            password_reset_confirm(
                token=s.validated_data["token"],
                new_password=s.validated_data["new_password"],
                ip=_get_ip(request),
            )
        except (TokenInvalidError, ApplicationError) as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Mot de passe réinitialisé. Veuillez vous reconnecter."})


class PasswordChangeApi(ApiAuthMixin, APIView):
    class InputSerializer(serializers.Serializer):
        current_password = serializers.CharField(write_only=True)
        new_password = serializers.CharField(min_length=8, write_only=True)

    @extend_schema(
        tags=["Authentification"],
        summary="Changement de mot de passe (Sud Mode)",
        description=(
            "Change le mot de passe de l'utilisateur connecté. "
            "**Paramètres d'entrée (JSON Body)** : `current_password`, `new_password`. "
            "Exige le mot de passe actuel (Sudo Mode). "
            "En cas de succès, TOUS les tokens JWT actifs sont invalidés (déconnexion globale)."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="Mot de passe changé"),
            400: OpenApiResponse(description="Mot de passe actuel incorrect ou nouveau trop faible"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            password_change(
                user=request.user,
                current_password=s.validated_data["current_password"],
                new_password=s.validated_data["new_password"],
                ip=_get_ip(request),
            )
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "detail": "Mot de passe modifié. Veuillez vous reconnecter sur tous vos appareils."
        })


# ===========================================================================
# CHANGEMENT D'EMAIL
# ===========================================================================

@extend_schema(tags=["Authentification"])
class EmailChangeRequestApi(ApiAuthMixin, APIView):
    """
    Initie le changement d'adresse email de l'utilisateur connecté (Sudo Mode).
    """
    class InputSerializer(serializers.Serializer):
        new_email = serializers.EmailField()
        current_password = serializers.CharField(write_only=True)

    @extend_schema(
        summary="Demande de changement d'email (Sudo Mode)",
        description=(
            "Initie le changement d'adresse email. "
            "**Paramètres d'entrée (JSON Body)** : `new_email`, `current_password`. "
            "Exige la vérification du mot de passe actuel (Sudo Mode). "
            "Envoie un code OTP à 6 chiffres à la **nouvelle** adresse uniquement. "
            "Le code expire après 10 minutes."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="OTP envoyé à la nouvelle adresse"),
            400: OpenApiResponse(description="Mot de passe incorrect ou email déjà utilisé"),
            429: OpenApiResponse(description="Trop de tentatives (Rate limiting IP/User)"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            email_change_request(
                user=request.user,
                new_email=s.validated_data["new_email"],
                current_password=s.validated_data["current_password"],
                ip=_get_ip(request),
            )
        except OtpRateLimitError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "detail": "Un code de vérification a été envoyé à votre nouvelle adresse email."
        })


@extend_schema(tags=["Authentification"])
class EmailChangeConfirmApi(ApiAuthMixin, APIView):
    """
    Confirme le changement d'email via un code OTP.
    """
    class InputSerializer(serializers.Serializer):
        otp_code = serializers.CharField(
            min_length=6, max_length=7,
            help_text="Code à 6 chiffres reçu par email (espaces autorisés : '123 456').",
        )

    @extend_schema(
        summary="Confirmation du changement d'email (OTP)",
        description=(
            "**Paramètres d'entrée (JSON Body)** : `otp_code`. "
            "Valide le code OTP reçu sur la nouvelle adresse. "
            "En cas de succès : l'email est mis à jour, tous les tokens JWT sont rotés (déconnexion de tous les appareils), "
            "et une notification est envoyée à l'ancienne adresse avec un lien de réversion."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="Email officiellement changé, reconnexion requise"),
            400: OpenApiResponse(description="Code incorrect ou expiré"),
            429: OpenApiResponse(description="Compte/IP verrouillé suite à trop d'échecs"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            email_change_confirm(
                user=request.user,
                otp_code=s.validated_data["otp_code"],
                ip=_get_ip(request),
            )
        except (OtpExpiredError, OtpInvalidError, OtpLockedError, ApplicationError) as exc:
            return _handle_otp_error(exc)

        return Response({
            "detail": "Email modifié. Veuillez vous reconnecter avec votre nouvelle adresse."
        })


class EmailChangeRevertApi(APIView):
    class InputSerializer(serializers.Serializer):
        token = serializers.CharField()

    @extend_schema(
        tags=["Authentification"],
        summary="Réversion d'urgence du changement d'email",
        description=(
            "Accessible sans authentification (l'attaquant a pu changer le mot de passe). "
            "Restaure l'ancienne adresse, invalide le mot de passe, révoque toutes les sessions. "
            "Lien valable 7 jours."
        ),
        request=InputSerializer,
        responses={
            200: OpenApiResponse(description="Email restauré, réinitialisation du mot de passe requise"),
            400: OpenApiResponse(description="Lien invalide ou expiré"),
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            email_change_revert(token=s.validated_data["token"], ip=_get_ip(request))
        except (TokenInvalidError, ApplicationError) as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "detail": (
                "Votre ancienne adresse email a été restaurée. "
                "Utilisez 'Mot de passe oublié' pour regagner l'accès à votre compte."
            )
        })


# ===========================================================================
# PROFIL
# ===========================================================================
# PROFIL (PROPRIÉTAIRE)
# ===========================================================================


@extend_schema(
    tags=["Profil"],
    summary="Mon profil",
    responses={200: MeOutputSerializer},
)
class UserMeDetailApi(ApiAuthMixin, APIView):
    def get(self, request):
        data = user_get_login_data(user=request.user)
        return Response(data)


@extend_schema(
    tags=["Profil"],
    summary="Mettre à jour mon profil",
    description=(
        "Met à jour les informations du profil de l'utilisateur connecté. "
        "Note : Les données du compte (email, rôle, mot de passe) ne peuvent PAS être modifiées ici. "
        "Le schéma des champs acceptés pour `profile` varie selon le rôle (Particulier ou Pro)."
    ),
    request=MeUpdateInputSerializer,
    responses={200: MeOutputSerializer},
)
class UserMeUpdateApi(ApiAuthMixin, APIView):
    def patch(self, request):
        s = MeUpdateInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user_update_profile(
                user=request.user,
                data=s.validated_data,
                performed_by=request.user,
                ip=_get_ip(request),
            )
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        data = user_get_login_data(user=request.user)
        return Response(data)


@extend_schema(
    tags=["Profil"],
    summary="Supprimer mon compte (soft)",
    description="Désactive et anonymise le compte. Les données de commandes sont conservées.",
    responses={204: OpenApiResponse(description="Compte supprimé")},
)
class UserMeDeleteApi(ApiAuthMixin, APIView):
    def delete(self, request):
        try:
            user_soft_delete(
                user=request.user,
                performed_by=request.user,
                ip=_get_ip(request),
            )
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


# ===========================================================================
# ADMINISTRATION
# ===========================================================================

@extend_schema(
    tags=["Admin"],
    summary="Liste des utilisateurs",
    description="Accessible aux staff et admin uniquement.",
    parameters=[
        OpenApiParameter("limit", int, description="Nombre d'éléments par page"),
        OpenApiParameter("offset", int, description="Index de début"),
        OpenApiParameter("email", str, description="Filtrer par email"),
        OpenApiParameter("role", str, description="Filtrer par rôle (super_admin, province_admin, diocese_admin, parish_admin, church_admin, fidele)"),
        OpenApiParameter("is_active", bool, description="Filtrer par statut actif"),
        OpenApiParameter("is_verified", bool, description="Filtrer par statut de vérification email"),
    ],
    responses={
        200: UserListPaginatedResponseSerializer,
        400: ErrorResponseSerializer,
        401: ErrorResponseSerializer,
        403: ErrorResponseSerializer,
    },
)
class UserListApi(ApiAuthMixin, APIView):
    permission_classes = [IsDioceseAdminOrAbove]

    class Pagination(LimitOffsetPagination):
        default_limit = 20

    class FilterSerializer(serializers.Serializer):
        id = serializers.UUIDField(required=False)
        email = serializers.EmailField(required=False)
        role = serializers.CharField(required=False)
        pastoral_role = serializers.CharField(required=False)
        is_active = serializers.BooleanField(required=False, allow_null=True, default=None)
        is_verified = serializers.BooleanField(required=False, allow_null=True, default=None)

    def get(self, request):
        filters_s = self.FilterSerializer(data=request.query_params)
        filters_s.is_valid(raise_exception=True)

        users = user_list(filters=filters_s.validated_data, for_user=request.user)

        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=UserListItemSerializer,
            queryset=users,
            request=request,
            view=self,
        )


class UserDetailApi(ApiAuthMixin, APIView):
    permission_classes = [IsStaffOrAdminUser]

    class OutputSerializer(serializers.Serializer):
        id = serializers.UUIDField()
        email = serializers.EmailField()
        phone_number = serializers.CharField()
        role = serializers.CharField()
        is_active = serializers.BooleanField()
        is_verified = serializers.BooleanField()
        is_admin = serializers.BooleanField()
        is_staff = serializers.BooleanField()
        date_joined = serializers.SerializerMethodField()
        user_profile = serializers.SerializerMethodField()
        address = serializers.SerializerMethodField()

        def get_date_joined(self, obj):
            return obj.created_at.isoformat() if obj.created_at else None

        def get_user_profile(self, obj):
            p = getattr(obj, "profile", None)
            if not p:
                return None
            return {
                "first_name": p.first_name,
                "last_name": p.last_name,
                "title": p.title,
                "date_of_birth": str(p.date_of_birth) if p.date_of_birth else None,
                "phone": str(p.phone) if p.phone else None,
                # FK Parish → {id, name} (objet brut = non sérialisable JSON, BUG-B1).
                # Même forme que UserListItemSerializer.get_user_profile : sans cette
                # projection, GET /users/{id}/ renvoyait 500 pour tout fidèle onboardé.
                "primary_parish": (
                    {"id": p.primary_parish_id, "name": p.primary_parish.name}
                    if p.primary_parish_id
                    else None
                ),
                "avatar": p.avatar.url if p.avatar else None,
            }

        def get_address(self, obj):
            return None

    @extend_schema(
        tags=["Admin"],
        summary="Détail d'un utilisateur",
        description="Fiche complète d'un compte. Accessible aux administrateurs.",
        request=None,  # GET : aucun corps de requête lu.
        responses={
            200: OutputSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request, user_id):
        user = user_get_with_profile(user_id)
        if user is None:
            raise Http404
        return Response(self.OutputSerializer(user).data)


class UserAdminCreateApi(ApiAuthMixin, APIView):
    permission_classes = [IsAdminUser]

    class InputSerializer(serializers.Serializer):
        email = serializers.EmailField()
        phone_number = serializers.CharField(max_length=20)
        role = serializers.ChoiceField(choices=UserRole.choices)
        first_name = serializers.CharField(max_length=50)
        last_name = serializers.CharField(max_length=50)
        title = serializers.CharField(max_length=10, required=False, default="")

    class OutputSerializer(serializers.Serializer):
        id = serializers.UUIDField()
        email = serializers.EmailField()
        role = serializers.CharField()

    @extend_schema(
        tags=["Admin"],
        summary="Créer un compte staff ou admin",
        description=(
            "Crée un compte immédiatement actif et vérifié. "
            "Un mot de passe temporaire est généré et envoyé par email. "
            "Accessible aux administrateurs uniquement."
        ),
        request=InputSerializer,
        responses={
            201: OutputSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
        },
    )
    def post(self, request):
        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            user = user_create_by_admin(
                **s.validated_data,
                performed_by=request.user,
                ip=_get_ip(request),
            )
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(self.OutputSerializer(user).data, status=status.HTTP_201_CREATED)


class UserToggleActiveApi(ApiAuthMixin, APIView):
    permission_classes = [IsDioceseAdminOrAbove]

    class InputSerializer(serializers.Serializer):
        is_active = serializers.BooleanField()

    class OutputSerializer(serializers.Serializer):
        detail = serializers.CharField()
        is_active = serializers.BooleanField()

    @extend_schema(
        tags=["Admin"],
        summary="Activer ou désactiver un compte",
        description="Bascule le statut d'activation d'un compte, dans le périmètre de l'appelant.",
        request=InputSerializer,
        responses={
            200: OutputSerializer,
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def patch(self, request, user_id):
        user = user_get(user_id)
        if user is None:
            raise Http404

        s = self.InputSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        try:
            user_toggle_active(
                user=user,
                is_active=s.validated_data["is_active"],
                performed_by=request.user,
                ip=_get_ip(request),
            )
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response({"detail": "Statut mis à jour.", "is_active": s.validated_data["is_active"]})


class UserSoftDeleteApi(ApiAuthMixin, APIView):
    permission_classes = [IsDioceseAdminOrAbove]

    @extend_schema(
        tags=["Admin"],
        summary="Suppression soft d'un utilisateur",
        description="Désactive et anonymise le compte. Les commandes sont conservées.",
        request=None,  # DELETE : aucun corps de requête lu.
        responses={
            204: OpenApiResponse(description="Compte supprimé (soft)"),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def delete(self, request, user_id):
        user = user_get(user_id)
        if user is None:
            raise Http404

        try:
            user_soft_delete(user=user, performed_by=request.user, ip=_get_ip(request))
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class UserHardDeleteApi(ApiAuthMixin, APIView):
    permission_classes = [IsAdminUser]

    @extend_schema(
        tags=["Admin"],
        summary="Suppression définitive d'un utilisateur",
        description="IRRÉVERSIBLE. Réservé aux administrateurs. L'audit log est conservé.",
        request=None,  # DELETE : aucun corps de requête lu.
        responses={
            204: OpenApiResponse(description="Compte supprimé définitivement"),
            400: ErrorResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def delete(self, request, user_id):
        user = user_get(user_id)
        if user is None:
            raise Http404

        try:
            user_hard_delete(user=user, performed_by=request.user, ip=_get_ip(request))
        except ApplicationError as exc:
            return Response({"detail": exc.message}, status=status.HTTP_400_BAD_REQUEST)

        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditLogItemSerializer(serializers.Serializer):
    event = serializers.CharField()
    ip_address = serializers.CharField(allow_null=True)
    metadata = serializers.DictField()
    created_at = serializers.DateTimeField()


class AuditLogPaginatedResponseSerializer(serializers.Serializer):
    limit = serializers.IntegerField()
    offset = serializers.IntegerField()
    count = serializers.IntegerField()
    next = serializers.URLField(allow_null=True)
    previous = serializers.URLField(allow_null=True)
    results = AuditLogItemSerializer(many=True)


class UserAuditLogApi(ApiAuthMixin, APIView):
    permission_classes = [IsDioceseAdminOrAbove]

    class Pagination(LimitOffsetPagination):
        default_limit = 50

    @extend_schema(
        tags=["Admin"],
        summary="Journal d'audit d'un utilisateur (paginé)",
        description=(
            "Historique des événements de sécurité, du plus récent au plus ancien. "
            "Paginé : un compte ancien peut porter des milliers d'entrées."
        ),
        request=None,  # GET : aucun corps de requête lu.
        parameters=[
            OpenApiParameter("limit", int, description="Nombre d'éléments par page (défaut 50)"),
            OpenApiParameter("offset", int, description="Index de début"),
        ],
        responses={
            200: AuditLogPaginatedResponseSerializer,
            401: ErrorResponseSerializer,
            403: ErrorResponseSerializer,
            404: ErrorResponseSerializer,
        },
    )
    def get(self, request, user_id):
        user = user_get(user_id)
        if user is None:
            raise Http404

        logs = audit_log_list(user=user)
        return get_paginated_response(
            pagination_class=self.Pagination,
            serializer_class=AuditLogItemSerializer,
            queryset=logs,
            request=request,
            view=self,
        )
