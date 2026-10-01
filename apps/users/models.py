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
        user = cast(
            "BaseUser",
            self.model(
                email=normalized_email,
                phone_number=phone_number,
                is_staff=is_staff,
                is_active=is_active,
                is_verified=is_verified,
                **extra_fields,
            ),
        )

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
    keycloak_sub = models.CharField(_("identifiant Keycloak"), max_length=64, unique=True, null=True, blank=True)
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
    declared_at = models.DateTimeField(_("déclaré le"), null=True, blank=True)
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
    # Présence (messagerie) : « vu à », écrit à la fermeture de la dernière connexion temps réel.
    last_seen_at = models.DateTimeField(_("vu à"), null=True, blank=True)
    # « Montrer ma présence » : vide = valeur par défaut (oui pour le clergé et le staff, non sinon).
    montrer_presence = models.BooleanField(_("montrer ma présence"), null=True, blank=True)

    # --- Administration des comptes et synchronisation Keycloak (docs/ADMIN-KEYCLOAK.md) ---
    # Nœud dont l'administration a créé le compte : il fixe la portée de gestion du compte
    # (avec les nœuds de ses nominations). Vide pour un fidèle inscrit seul : la plateforme.
    admin_node = models.ForeignKey(
        "hierarchy.Node",
        verbose_name=_("nœud gestionnaire du compte"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="administered_accounts",
    )
    # Miroir du rôle de realm ``platform_admin`` (lu par la synchronisation) : sert aux contrôles
    # de portée sans appel réseau. L'autorisation réelle vient toujours du jeton.
    keycloak_platform_admin = models.BooleanField(
        _("administrateur plateforme (Keycloak)"), default=False, db_default=False
    )
    keycloak_synced_at = models.DateTimeField(_("synchronisé avec Keycloak le"), null=True, blank=True)
    keycloak_sync_error = models.CharField(
        _("écart de synchronisation"), max_length=64, blank=True, default="", db_default=""
    )

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


# ---------------------------------------------------------------------------
# Synchronisation Keycloak (docs/ADMIN-KEYCLOAK.md)
# ---------------------------------------------------------------------------


class KeycloakEventStatus(models.TextChoices):
    RECU = "recu", _("Reçu")
    TRAITE = "traite", _("Traité")
    IGNORE = "ignore", _("Ignoré")
    ECHEC = "echec", _("Échec")


class KeycloakEvent(models.Model):
    """Événement reçu du SPI Keycloak (webhook signé). On ne garde que le nécessaire au
    traitement idempotent : identifiant, type, compte concerné. Jamais la représentation."""

    uid = models.CharField(_("identifiant de l'événement"), max_length=128, unique=True)
    event_type = models.CharField(_("type"), max_length=80)
    keycloak_user_id = models.CharField(_("compte Keycloak"), max_length=64, blank=True, default="", db_index=True)
    status = models.CharField(
        max_length=10, choices=KeycloakEventStatus.choices, default=KeycloakEventStatus.RECU, db_index=True
    )
    result = models.CharField(max_length=64, blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("événement Keycloak")
        verbose_name_plural = _("événements Keycloak")
        ordering = ["-received_at"]

    def __str__(self) -> str:
        return f"{self.event_type} {self.uid}"


class KeycloakSyncRun(models.Model):
    """Passe de réconciliation Keycloak ↔ application, avec son rapport."""

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    dry_run = models.BooleanField(default=True)
    trigger = models.CharField(max_length=20, default="tache")  # tache | commande | admin
    triggered_by = models.ForeignKey(BaseUser, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    success = models.BooleanField(default=False)
    error = models.CharField(max_length=255, blank=True, default="")
    counts = models.JSONField(default=dict, blank=True)
    report = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = _("réconciliation Keycloak")
        verbose_name_plural = _("réconciliations Keycloak")
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Réconciliation {self.started_at:%Y-%m-%d %H:%M}"


class KeycloakSyncCursor(models.Model):
    """Curseur de lecture des événements Keycloak (Admin REST API) : horodatage (ms) du dernier
    événement traité, par flux (``utilisateur``, ``admin``)."""

    name = models.CharField(max_length=20, unique=True)
    last_event_ms = models.BigIntegerField(default=0)
    last_polled_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        verbose_name = _("curseur des événements Keycloak")
        verbose_name_plural = _("curseurs des événements Keycloak")

    def __str__(self) -> str:
        return f"{self.name} @ {self.last_event_ms}"
