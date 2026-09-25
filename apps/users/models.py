import uuid
from typing import cast

from django.contrib.auth.models import AbstractBaseUser, Group, Permission, PermissionsMixin
from django.contrib.auth.models import BaseUserManager as DjangoBaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _
from phonenumber_field.modelfields import PhoneNumberField

from apps.common.models import BaseModel
from apps.hierarchy.enums import DegreOrdre, EtatDeVie, StatutVerification
from apps.users.enums import (
    AuditEvent,
    ClergyValidationStatus,
    PastoralRole,
    RoleScope,
    Title,
    UserOnboardingState,
    UserRole,
)

# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class BaseUserManager(DjangoBaseUserManager):
    def create_user(
        self,
        email: str,
        role: str,
        phone_number: str | None,
        password: str | None = None,
        is_verified: bool = False,
        is_active: bool = False,
        is_staff: bool = False,
        is_admin: bool = False,
        **extra_fields,
    ) -> "BaseUser":
        if not email:
            raise ValueError("L'adresse email est obligatoire.")
        if not role:
            raise ValueError("Le rôle est obligatoire.")

        normalized_email = self.normalize_email(email).lower()

        # cast : django-stubs type self.model() en "_T" générique dans BaseUserManager,
        # ce qui masque les méthodes AbstractBaseUser (set_password, etc.).
        user = cast("BaseUser", self.model(
            email=normalized_email,
            phone_number=phone_number,
            role=role,
            is_staff=is_staff,
            is_active=is_active,
            is_admin=is_admin,
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
        phone_number: str = "+221771000000",
        **extra_fields,
    ) -> "BaseUser":
        return self.create_user(
            email=email,
            password=password,
            phone_number=phone_number,
            role=UserRole.SUPER_ADMIN,
            is_superuser=True,
            is_staff=True,
            is_admin=True,
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
    role = models.CharField(
        _("rôle"),
        max_length=20,
        choices=UserRole.choices,
        db_index=True,
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
    is_admin = models.BooleanField(
        _("administrateur"),
        default=False,
    )

    # UUID rotatif : invalide TOUS les JWT actifs de l'utilisateur en une mise à jour
    jwt_key = models.UUIDField(
        default=uuid.uuid4,
        help_text=_("Rotation invalide tous les tokens JWT actifs."),
    )

    # Dimension pastorale (clergé/fidèle — orthogonale au rôle admin)
    pastoral_role = models.CharField(
        _("rôle pastoral"),
        max_length=20,
        choices=PastoralRole.choices,
        null=True,
        blank=True,
        db_index=True,
    )

    # Validation hiérarchique du compte clergé (chaîne de validation SRS).
    # Un compte issu d'une INVITATION naît APPROVED (accepter le token vaut
    # validation) ; une AUTO-DÉCLARATION naît PENDING et attend l'approbation du
    # supérieur territorial. Les laïcs restent NOT_APPLICABLE.
    clergy_validation_status = models.CharField(
        _("validation du compte clergé"),
        max_length=20,
        choices=ClergyValidationStatus.choices,
        default=ClergyValidationStatus.NOT_APPLICABLE,
        db_index=True,
    )

    # Onboarding — état du parcours d'inscription
    onboarding_state = models.CharField(
        _("état onboarding"),
        max_length=30,
        choices=UserOnboardingState.choices,
        default=UserOnboardingState.PENDING_EMAIL_VERIFICATION,
        db_index=True,
    )

    # Hiérarchie territoriale (auto-remplie par signal depuis Profile.primary_parish)
    diocese = models.ForeignKey(
        "org.Diocese",
        verbose_name=_("diocèse"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    province = models.ForeignKey(
        "org.Province",
        verbose_name=_("province"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
    )
    religious_community = models.ForeignKey(
        "org.ReligiousCommunity",
        verbose_name=_("communauté religieuse"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="members",
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
    REQUIRED_FIELDS = ["phone_number"]

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

    def rotate_jwt_key(self) -> None:
        """Invalide tous les JWT actifs. Appelé après password change / email change revert."""
        self.jwt_key = uuid.uuid4()
        self.save(update_fields=["jwt_key", "updated_at"])

    def get_scope_ids(self) -> dict:
        """IDs territoriaux pour le scoping du contenu, dérivés des appartenances
        (multi-appartenance, Chantier 3a). Renvoie des ENSEMBLES pluriels ; un
        fidèle sans appartenance obtient des ensembles vides. Un seul SELECT avec
        jointures (pas de N+1)."""
        rows = Membership.objects.filter(user=self).values_list(
            "church_id", "church__parish_id", "church__parish__diocese_id"
        )
        church_ids: set[int] = set()
        parish_ids: set[int] = set()
        diocese_ids: set[int] = set()
        for church_id, parish_id, diocese_id in rows:
            if church_id is not None:
                church_ids.add(church_id)
            if parish_id is not None:
                parish_ids.add(parish_id)
            if diocese_id is not None:
                diocese_ids.add(diocese_id)
        return {
            "church_ids": list(church_ids),
            "parish_ids": list(parish_ids),
            "diocese_ids": list(diocese_ids),
        }


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

    primary_parish = models.ForeignKey(
        "org.Parish",
        verbose_name=_("paroisse principale"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="primary_members",
    )

    class Meta:
        verbose_name = _("profil")
        verbose_name_plural = _("profils")

    def __str__(self) -> str:
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or str(self.user.email)


# ---------------------------------------------------------------------------
# Journal d'audit sécurité (SQL immuable — jamais supprimé)
# ---------------------------------------------------------------------------

class SecurityAuditLog(BaseModel):
    """
    Trace immuable de tous les événements de sécurité.
    Stockage SQL (Cold Data) — complémentaire au Hot Data Redis des OTP.
    Conforme OWASP ASVS V7.
    """

    user = models.ForeignKey(
        BaseUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        help_text=_("NULL si l'utilisateur a été supprimé définitivement."),
    )
    event = models.CharField(
        _("événement"),
        max_length=50,
        choices=AuditEvent.choices,
        db_index=True,
    )
    ip_address = models.GenericIPAddressField(
        _("adresse IP"),
        null=True,
        blank=True,
        help_text=_("IPv4 ou IPv6 nettoyée par le reverse proxy."),
    )
    user_agent = models.TextField(_("user agent"), blank=True, default="")
    metadata = models.JSONField(
        _("métadonnées"),
        default=dict,
        blank=True,
        help_text=_("Données contextuelles non sensibles (ex: nouvelle email masquée)."),
    )

    class Meta:
        verbose_name = _("journal de sécurité")
        verbose_name_plural = _("journaux de sécurité")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "event"]),
            models.Index(fields=["event", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"[{self.event}] {self.user} — {self.created_at:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# Affectation de rôle scopée territorialement (RBAC)
# ---------------------------------------------------------------------------

class RoleAssignment(BaseModel):
    """
    Capacité administrative d'un utilisateur, scopée à un niveau territorial.

    Dimension orthogonale à ``pastoral_role`` (identité dans l'Église). Un même
    utilisateur peut cumuler plusieurs affectations. Exemples :
    - curé de la paroisse A  → role=PARISH_ADMIN, scope=PARISH, parish=A, is_principal=True
    - vicaire à l'église B   → role=CHURCH_ADMIN, scope=CHURCH, church=B
    - évêque du diocèse D     → role=DIOCESE_ADMIN, scope=DIOCESE, diocese=D
    - super admin             → role=SUPER_ADMIN, scope=GLOBAL

    Les classes de permission consultent ces affectations pour le cloisonnement
    territorial (un curé de A ne voit pas les données de B).
    """

    user = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("utilisateur"),
        on_delete=models.CASCADE,
        related_name="role_assignments",
    )
    role = models.CharField(
        _("rôle / capacité"),
        max_length=20,
        choices=UserRole.choices,
        db_index=True,
    )
    scope = models.CharField(
        _("niveau de portée"),
        max_length=20,
        choices=RoleScope.choices,
        db_index=True,
    )
    province = models.ForeignKey(
        "org.Province",
        verbose_name=_("province"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
    )
    diocese = models.ForeignKey(
        "org.Diocese",
        verbose_name=_("diocèse"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
    )
    parish = models.ForeignKey(
        "org.Parish",
        verbose_name=_("paroisse"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
    )
    church = models.ForeignKey(
        "org.Church",
        verbose_name=_("église"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="role_assignments",
    )
    is_principal = models.BooleanField(
        _("titulaire principal"),
        default=False,
        help_text=_("Curé principal de la paroisse / responsable principal de l'église."),
    )
    is_active = models.BooleanField(_("active"), default=True, db_index=True)
    start_date = models.DateField(_("date de début"), null=True, blank=True)
    end_date = models.DateField(_("date de fin"), null=True, blank=True)
    note = models.CharField(_("note"), max_length=255, blank=True, default="")
    granted_by = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("attribuée par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_role_assignments",
    )

    class Meta:
        verbose_name = _("affectation de rôle")
        verbose_name_plural = _("affectations de rôle")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["role", "scope"]),
            models.Index(fields=["parish", "is_active"]),
            models.Index(fields=["diocese", "is_active"]),
            models.Index(fields=["church", "is_active"]),
        ]
        constraints = [
            # Un seul curé principal actif par paroisse
            models.UniqueConstraint(
                fields=["parish"],
                condition=models.Q(is_principal=True, is_active=True, scope="parish"),
                name="unique_active_principal_per_parish",
            ),
        ]

    def __str__(self) -> str:
        target = self.church_id or self.parish_id or self.diocese_id or self.province_id or "global"
        return f"{self.user_id} · {self.role}@{self.scope}:{target}"

    @property
    def scope_target_id(self):
        """ID de l'entité territoriale ciblée selon le scope (ou None pour global)."""
        return {
            RoleScope.PROVINCE: self.province_id,
            RoleScope.DIOCESE: self.diocese_id,
            RoleScope.PARISH: self.parish_id,
            RoleScope.CHURCH: self.church_id,
        }.get(self.scope)


# ---------------------------------------------------------------------------
# Appartenance ecclésiale (multi-appartenance) — couche ADDITIVE (Chantier 1)
# ---------------------------------------------------------------------------

class Membership(BaseModel):
    """
    Appartenance d'un utilisateur à une église (lieu de culte).

    Un fidèle peut appartenir à plusieurs églises (multi-appartenance). Au plus
    une appartenance est marquée principale (``is_primary``) : c'est elle qui
    pilote la hiérarchie territoriale dérivée de l'utilisateur
    (``BaseUser.diocese`` / ``province``) et, en miroir transitoire,
    ``Profile.primary_parish``.

    Couche ADDITIVE introduite au Chantier 1 : elle coexiste avec le chemin
    historique ``Profile.primary_parish`` + son signal. Le cutover (primary_parish
    dérivé de l'appartenance principale, retrait du vieux signal) est réservé au
    Chantier 2. L'invariant « exactement une appartenance principale tant qu'il
    reste ≥ 1 appartenance » est tenu par les services (``services_memberships``)
    ; la base garantit « au plus une principale par utilisateur » via une
    contrainte d'unicité partielle.
    """

    user = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("utilisateur"),
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    church = models.ForeignKey(
        "org.Church",
        verbose_name=_("église"),
        on_delete=models.CASCADE,
        related_name="member_links",
    )
    is_primary = models.BooleanField(
        _("appartenance principale"),
        default=False,
        db_index=True,
        help_text=_("Église de référence : pilote diocèse/province et primary_parish."),
    )

    class Meta:
        verbose_name = _("appartenance")
        verbose_name_plural = _("appartenances")
        ordering = ["-is_primary", "created_at"]
        indexes = [
            models.Index(fields=["user", "is_primary"]),
            models.Index(fields=["church"]),
        ]
        constraints = [
            # Pas deux fois la même église pour un même utilisateur.
            models.UniqueConstraint(
                fields=["user", "church"],
                name="unique_membership_user_church",
            ),
            # Au plus une appartenance principale par utilisateur.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_primary=True),
                name="unique_primary_membership_per_user",
            ),
        ]

    def __str__(self) -> str:
        flag = " ★" if self.is_primary else ""
        return f"{self.user_id} · église {self.church_id}{flag}"


# ---------------------------------------------------------------------------
# Auto-déclaration de clergé (seconde voie de la chaîne de validation SRS)
# ---------------------------------------------------------------------------

class ClergySelfDeclaration(BaseModel):
    """Demande par laquelle un utilisateur inscrit REVENDIQUE un rôle pastoral.

    C'est le maillon qui rend la file de validation atteignable : la voie
    *invitation* (``apps.clergy_accounts``) naît ``APPROVED`` — accepter le token
    vaut validation — donc aucun compte n'arrivait jamais en ``PENDING``.

    **Pourquoi le rôle revendiqué vit ICI et non dans ``BaseUser.pastoral_role``**
    — c'est LE point de sécurité de ce modèle. ``pastoral_role`` n'est pas une
    simple étiquette : il est lu, seul et sans jamais consulter
    ``clergy_validation_status``, comme preuve d'appartenance au clergé par au
    moins douze modules — ``IsOnboardingCompleted`` (garde des écritures
    territoriales), la signature de documents (``apps.documents.services``), la
    publication d'actualités (``apps.news.services``), la messagerie inter-clergé,
    les intentions de messe, les campagnes de dons, la catégorie TV « Formation »,
    la Liturgie des Heures. Poser ``pastoral_role = PRETRE`` à la seconde où
    quelqu'un se déclare aurait donc livré, en libre-service et avant toute
    revue humaine, l'intégralité des capacités cléricales : une escalade de
    privilèges, pas une demande.

    Tant que la demande est ``PENDING``, l'utilisateur reste donc **strictement un
    laïc** dans toutes les couches d'autorisation. ``pastoral_role`` n'est écrit
    qu'à l'approbation, par ``user_validate_clergy_account``. C'est le pendant
    exact du raisonnement de ``user_reject_clergy_account``, qui RETIRE le rôle
    au refus pour la même raison.
    """

    class Status(models.TextChoices):
        PENDING  = ("pending",  _("En attente de validation"))
        APPROVED = ("approved", _("Approuvée"))
        REJECTED = ("rejected", _("Refusée"))

    user = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("demandeur"),
        on_delete=models.CASCADE,
        related_name="clergy_declarations",
    )
    claimed_pastoral_role = models.CharField(
        _("rôle pastoral revendiqué"),
        max_length=20,
        choices=PastoralRole.choices,
        db_index=True,
        help_text=_("Revendication SANS effet tant qu'elle n'est pas approuvée."),
    )
    parish = models.ForeignKey(
        "org.Parish",
        verbose_name=_("paroisse de rattachement"),
        on_delete=models.PROTECT,
        related_name="clergy_declarations",
        help_text=_("Territoire revendiqué : détermine l'autorité compétente."),
    )
    justification_file = models.ForeignKey(
        "files.File",
        verbose_name=_("justificatif"),
        on_delete=models.PROTECT,
        related_name="clergy_declarations",
        help_text=_("Pièce justificative — un fichier n'est valide qu'une fois téléversé."),
    )
    message = models.TextField(
        _("message du demandeur"),
        blank=True,
        default="",
        help_text=_("Précisions facultatives adressées à l'autorité validante."),
    )
    status = models.CharField(
        _("statut"),
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        "users.BaseUser",
        verbose_name=_("tranchée par"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_clergy_declarations",
    )
    reviewed_at = models.DateTimeField(_("date de décision"), null=True, blank=True)
    rejection_reason = models.CharField(
        _("motif du refus"),
        max_length=500,
        blank=True,
        default="",
        help_text=_("Restitué au demandeur : il doit pouvoir corriger et resoumettre."),
    )

    class Meta:
        verbose_name = _("auto-déclaration de clergé")
        verbose_name_plural = _("auto-déclarations de clergé")
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "status"]),
            models.Index(fields=["parish", "status"]),
        ]
        constraints = [
            # Une seule demande en cours par utilisateur : la re-soumission est
            # interdite tant que rien n'a été tranché, autorisée après un refus.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="pending"),
                name="unique_pending_clergy_declaration_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"Déclaration({self.user_id} → {self.claimed_pastoral_role}) [{self.status}]"
