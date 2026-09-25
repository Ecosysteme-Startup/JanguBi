import uuid
from typing import cast

from django.contrib.auth.models import AbstractBaseUser, Group, Permission, PermissionsMixin
from django.contrib.auth.models import BaseUserManager as DjangoBaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from apps.common.models import BaseModel
from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
from apps.users.enums import Title

# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class BaseUserManager(DjangoBaseUserManager):
    def create_user(
        self,
        email: str,
        phone_number: str | None = None,
        password: str | None = None,
        is_verified: bool = False,
        is_active: bool = False,
        is_staff: bool = False,
        **extra_fields,
    ) -> "BaseUser":
        if not email:
            raise ValueError("L'adresse email est obligatoire.")

        normalized_email = self.normalize_email(email).lower()

        # cast : django-stubs type self.model() en "_T" générique dans BaseUserManager,
        # ce qui masque les méthodes AbstractBaseUser (set_password, etc.).
        user = cast("BaseUser", self.model(
            email=normalized_email,
            phone_number=phone_number,
            is_staff=is_staff,
            is_active=is_active,
            is_verified=is_verified,
            **extra_fields,
        ))

        if password is not None:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.full_clean()
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        email: str,
        password: str,
        phone_number: str | None = None,
        **extra_fields,
    ) -> "BaseUser":
        """Compte de l'admin Django (exploitation). Ne donne AUCUN droit dans l'API :
        l'administrateur plateforme est le rôle Keycloak ``platform_admin`` (ADR-015)."""
        return self.create_user(
            email=email,
            password=password,
            phone_number=phone_number,
            is_superuser=True,
            is_staff=True,
            is_verified=True,
            is_active=True,
            **extra_fields,
        )


# ---------------------------------------------------------------------------
# Modèle utilisateur principal
# ---------------------------------------------------------------------------

class BaseUser(BaseModel, AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(
        verbose_name=_("adresse email"),
        max_length=255,
        unique=True,
        db_index=True,
    )
    phone_number = PhoneNumberField(
        _("numéro de téléphone"),
        unique=True,
        db_index=True,
        # Facultatif depuis L3 : un compte créé par Keycloak n'a pas de téléphone.
        null=True,
        blank=True,
    )
    is_verified = models.BooleanField(
        _("email vérifié"),
        default=False,
        help_text=_("L'utilisateur a validé son adresse email."),
    )
    is_active = models.BooleanField(
        _("actif"),
        default=False,
        help_text=_("Désactivez plutôt que de supprimer le compte."),
    )
    is_staff = models.BooleanField(
        _("membre du staff"),
        default=False,
        help_text=_("Accès à l'interface d'administration Django."),
    )
    # --- Personne V1 (SRS §5.2, ADR-003) : état de vie, vérification, paroisse suivie ---
    keycloak_sub = models.CharField(
        _("identifiant Keycloak"), max_length=64, unique=True, null=True, blank=True
    )
    etat_de_vie = models.CharField(
        _("état de vie"),
        max_length=10,
        choices=EtatDeVie.choices,
        default=EtatDeVie.LAIC,
        db_default=EtatDeVie.LAIC,
    )
    degre_ordre = models.CharField(
        _("degré d'ordre"),
        max_length=20,
        choices=DegreOrdre.choices,
        default=DegreOrdre.AUCUN,
        db_default=DegreOrdre.AUCUN,
    )
    incardination_node = models.ForeignKey(
        "hierarchy.Node",
        verbose_name=_("incardination"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="incardinated_people",
    )
    institut_node = models.ForeignKey(
        "hierarchy.Node",
        verbose_name=_("institut"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="consecrated_members",
    )
    statut_verification = models.CharField(
        _("statut de vérification"),
        max_length=10,
        choices=StatutVerification.choices,
        default=StatutVerification.DECLARE,
        db_default=StatutVerification.DECLARE,
    )
    verification_note = models.CharField(
        _("note de vérification"), max_length=255, blank=True, default="", db_default=""
    )
    verified_by = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("vérifié par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(_("vérifié le"), null=True, blank=True)
    paroisse_suivie = models.ForeignKey(
        "hierarchy.Node",
        verbose_name=_("paroisse suivie"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="followers",
    )
    consent_version = models.CharField(
        _("version du consentement"), max_length=20, blank=True, default="", db_default=""
    )
    consent_at = models.DateTimeField(_("consentement le"), null=True, blank=True)
    # Activité au jour près (tableaux de bord, EF-DASH-01/03) : une écriture par jour au plus.
    last_seen_on = models.DateField(_("dernière activité le"), null=True, blank=True)
    last_mfa_on = models.DateField(_("dernière connexion MFA le"), null=True, blank=True)

    groups = models.ManyToManyField(  # type: ignore[assignment]  # django-stubs : redéclaration M2M de PermissionsMixin (related_name custom)
        Group,
        verbose_name=_("groupes"),
        blank=True,
        related_name="baseuser_set",
    )
    user_permissions = models.ManyToManyField(  # type: ignore[assignment]  # django-stubs : redéclaration M2M de PermissionsMixin (related_name custom)
        Permission,
        verbose_name=_("permissions"),
        blank=True,
        related_name="baseuser_permissions_set",
    )

    objects = BaseUserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []  # type: ignore[var-annotated]  # AbstractBaseUser déclare déjà la variable de classe

    class Meta:
        verbose_name = _("utilisateur")
        verbose_name_plural = _("utilisateurs")
        indexes = [
            # File de vérification (EF-PER-02) : les laïcs, majoritaires, en sont exclus.
            models.Index(
                fields=["statut_verification"],
                condition=~models.Q(etat_de_vie="laic"),
                name="users_verification_queue",
            ),
            # Tableaux de bord (EF-DASH-01/03) : fenêtres d'activité.
            models.Index(fields=["last_seen_on"], name="users_last_seen_idx"),
            models.Index(fields=["last_mfa_on"], name="users_last_mfa_idx"),
        ]

    def __str__(self) -> str:
        return self.email


# ---------------------------------------------------------------------------
# Profil utilisateur
# ---------------------------------------------------------------------------

class Profile(BaseModel):
    user = models.OneToOneField(
        BaseUser,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    first_name = models.CharField(_("prénom"), max_length=50, blank=True, default="")
    last_name = models.CharField(_("nom"), max_length=50, blank=True, default="")
    title = models.CharField(
        _("civilité"),
        max_length=10,
        choices=Title.choices,
        blank=True,
        default="",
    )
    date_of_birth = models.DateField(_("date de naissance"), null=True, blank=True)
    phone = PhoneNumberField(_("téléphone"), blank=True, null=True)
    avatar = models.ImageField(_("avatar"), upload_to="avatars/", blank=True, null=True)

    class Meta:
        verbose_name = _("profil")
        verbose_name_plural = _("profils")

    def __str__(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or str(self.user.email)
