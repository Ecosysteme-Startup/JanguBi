"""
Autorité de scoping territorial (lecture seule).

Source de vérité du cloisonnement RBAC : qui peut agir sur quoi, à quel niveau
territorial. Consommé par les selectors et les classes de permission de toutes
les apps.

L'autorité se résout selon DEUX dimensions orthogonales, dont **l'une suffit** :

- **administrative** — ``RoleAssignment`` actives (``user_can_admin_*``,
  ``accessible_*_ids``, ``is_any_admin``) ;
- **pastorale** — la charge elle-même (``user_has_pastoral_authority``), dérivée
  du ``pastoral_role`` et des appartenances réelles (``Membership``). Un curé
  validé peut porter ``pastoral_role=PRETRE`` sans aucune ``RoleAssignment`` : la
  seule voie administrative lui refusait alors sa propre paroisse.

Convention : les fonctions ``accessible_*_ids`` renvoient ``None`` pour signifier
« aucune restriction » (administrateur global / super_admin), ou un ``set`` d'IDs
autorisés sinon.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet

from apps.org.models import Church, Diocese, Parish, Province
from apps.users.enums import PastoralRole, RoleScope, UserRole
from apps.users.models import BaseUser, RoleAssignment

# ---------------------------------------------------------------------------
# Scoping de contenu (multi-appartenance) — générique, réutilisable
# ---------------------------------------------------------------------------

# Vocabulaire de portée partagé par les contenus scopés (Article, Event, …).
# Doit rester aligné avec les ScopeType de chaque modèle (mêmes valeurs).
SCOPE_GLOBAL = "global"
SCOPE_DIOCESE = "diocese"
SCOPE_PARISH = "parish"
SCOPE_CHURCH = "church"


def get_scoped_queryset(qs: QuerySet, user) -> QuerySet:
    """Restreint ``qs`` (modèle scopé : ``scope_type`` + FK
    ``scope_church``/``scope_parish``/``scope_diocese``) à ce que ``user`` peut voir,
    d'après ses appartenances : global ∪ église∈church_ids ∪ paroisse∈parish_ids ∪
    diocèse∈diocese_ids. Helper générique consommé par les feeds (Article ici,
    Event au Chantier 3b)."""
    scope = user.get_scope_ids()
    filters = Q(scope_type=SCOPE_GLOBAL)
    if scope["church_ids"]:
        filters |= Q(scope_type=SCOPE_CHURCH, scope_church_id__in=scope["church_ids"])
    if scope["parish_ids"]:
        filters |= Q(scope_type=SCOPE_PARISH, scope_parish_id__in=scope["parish_ids"])
    if scope["diocese_ids"]:
        filters |= Q(scope_type=SCOPE_DIOCESE, scope_diocese_id__in=scope["diocese_ids"])
    return qs.filter(filters)


# ---------------------------------------------------------------------------
# Affectations actives
# ---------------------------------------------------------------------------

def active_role_assignments(user) -> QuerySet[RoleAssignment]:
    if not user or not getattr(user, "is_authenticated", False):
        return RoleAssignment.objects.none()
    return user.role_assignments.filter(is_active=True)


def is_global_admin(user) -> bool:
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) == UserRole.SUPER_ADMIN:
        return True
    # La PORTÉE est aussi déterminante que le rôle : sans `scope=GLOBAL`, une
    # RoleAssignment(role=super_admin, scope=parish) — créable par tout admin de
    # paroisse sur sa propre paroisse — conférait l'autorité globale sur toute
    # la plateforme (audit beta 2026-07-20). `services_roles` refuse désormais
    # ce couple ; ce filtre neutralise en plus les lignes déjà en base.
    return (
        active_role_assignments(user)
        .filter(role=UserRole.SUPER_ADMIN, scope=RoleScope.GLOBAL)
        .exists()
    )


# Rôles d'administration digitale (UserRole). Source de vérité = RoleAssignment :
# un curé porteur d'une RoleAssignment(parish_admin) est admin même si user.role
# est resté 'fidele'.
_ANY_ADMIN_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.PROVINCE_ADMIN,
    UserRole.DIOCESE_ADMIN,
    UserRole.PARISH_ADMIN,
    UserRole.CHURCH_ADMIN,
}


def is_any_admin(user) -> bool:
    """Vrai si l'utilisateur possède une capacité admin, par ``user.role`` OU par
    une ``RoleAssignment`` admin active. Permet aux endpoints view-level d'admettre
    le clergé scopé (curé avec RoleAssignment, user.role='fidele') ; l'autorité
    territoriale fine reste décidée par ``user_can_admin_*`` / ``accessible_*_ids``.
    """
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "role", None) in _ANY_ADMIN_ROLES:
        return True
    return active_role_assignments(user).filter(role__in=_ANY_ADMIN_ROLES).exists()


def role_assignment_get(*, assignment_id: int) -> RoleAssignment | None:
    """Une affectation par ID, chaîne église préchargée (``None`` si absente).

    Isole l'accès ORM hors de la couche API (``apis_roles``), conformément à la
    séparation des couches HackSoft. Sémantique identique à un ``.first()``.
    """
    return RoleAssignment.objects.select_related("church").filter(id=assignment_id).first()


# Lectures territoriales ponctuelles utilisées par la couche API de ce module.
# Elles renvoient ``None`` (et non une exception) : les vues distinguent 404
# « cible introuvable » de 403 « hors périmètre ».

def org_province_get(*, province_id) -> Province | None:
    return Province.objects.filter(id=province_id).first()


def org_diocese_get(*, diocese_id) -> Diocese | None:
    return Diocese.objects.filter(id=diocese_id).first()


def org_parish_get(*, parish_id) -> Parish | None:
    return Parish.objects.filter(id=parish_id).first()


def org_church_get(*, church_id) -> Church | None:
    return Church.objects.select_related("parish").filter(id=church_id).first()


def role_assignment_list(*, user=None) -> QuerySet[RoleAssignment]:
    qs = RoleAssignment.objects.select_related(
        "user", "province", "diocese", "parish", "church", "granted_by"
    )
    if user is not None:
        qs = qs.filter(user=user)
    return qs.order_by("-created_at")


# ---------------------------------------------------------------------------
# Ensembles d'IDs accessibles (None = illimité)
# ---------------------------------------------------------------------------

def accessible_province_ids(user) -> set[int] | None:
    if is_global_admin(user):
        return None
    ids = {
        pid
        for pid in active_role_assignments(user)
        .filter(scope=RoleScope.PROVINCE)
        .values_list("province_id", flat=True)
        if pid is not None
    }
    return ids


def accessible_diocese_ids(user) -> set[int] | None:
    if is_global_admin(user):
        return None
    ras = active_role_assignments(user)
    diocese_ids = {
        did
        for did in ras.filter(scope=RoleScope.DIOCESE).values_list("diocese_id", flat=True)
        if did is not None
    }
    province_ids = {
        pid
        for pid in ras.filter(scope=RoleScope.PROVINCE).values_list("province_id", flat=True)
        if pid is not None
    }
    if province_ids:
        diocese_ids |= set(
            Diocese.objects.filter(province_id__in=province_ids).values_list("id", flat=True)
        )
    return diocese_ids


def accessible_parish_ids(user) -> set[int] | None:
    if is_global_admin(user):
        return None
    ras = active_role_assignments(user)
    parish_ids = {
        pid
        for pid in ras.filter(scope=RoleScope.PARISH).values_list("parish_id", flat=True)
        if pid is not None
    }
    church_ids = {
        cid
        for cid in ras.filter(scope=RoleScope.CHURCH).values_list("church_id", flat=True)
        if cid is not None
    }
    if church_ids:
        parish_ids |= set(
            Church.objects.filter(id__in=church_ids).values_list("parish_id", flat=True)
        )
    diocese_ids = accessible_diocese_ids(user)  # set (jamais None ici)
    if diocese_ids:
        parish_ids |= set(
            Parish.objects.filter(diocese_id__in=diocese_ids).values_list("id", flat=True)
        )
    return parish_ids


# ---------------------------------------------------------------------------
# Vérifications ponctuelles d'autorité
# ---------------------------------------------------------------------------

def user_can_admin_parish(user, parish_id: int) -> bool:
    if is_global_admin(user):
        return True
    try:
        parish = Parish.objects.select_related("diocese").get(id=parish_id)
    except Parish.DoesNotExist:
        return False
    ras = active_role_assignments(user)
    if ras.filter(scope=RoleScope.PARISH, parish_id=parish_id).exists():
        return True
    if ras.filter(scope=RoleScope.DIOCESE, diocese_id=parish.diocese_id).exists():
        return True
    if ras.filter(scope=RoleScope.PROVINCE, province_id=parish.diocese.province_id).exists():
        return True
    return False


def user_can_admin_church(user, church_id: int) -> bool:
    """Autorité sur une église X (RG-CONT Chantier 3b). Vrai si :
    admin global, OU RoleAssignment scope=church sur X, OU autorité sur la PAROISSE
    de X (parish/diocese/province au-dessus). → un church_admin scopé sur X PEUT
    publier sur X, sans exiger l'autorité paroisse."""
    if is_global_admin(user):
        return True
    try:
        church = Church.objects.select_related("parish").get(id=church_id)
    except Church.DoesNotExist:
        return False
    if active_role_assignments(user).filter(
        scope=RoleScope.CHURCH, church_id=church_id
    ).exists():
        return True
    return user_can_admin_parish(user, church.parish_id)


def user_can_admin_diocese(user, diocese_id: int) -> bool:
    if is_global_admin(user):
        return True
    try:
        diocese = Diocese.objects.get(id=diocese_id)
    except Diocese.DoesNotExist:
        return False
    ras = active_role_assignments(user)
    if ras.filter(scope=RoleScope.DIOCESE, diocese_id=diocese_id).exists():
        return True
    if ras.filter(scope=RoleScope.PROVINCE, province_id=diocese.province_id).exists():
        return True
    return False


def user_can_admin_province(user, province_id: int) -> bool:
    if is_global_admin(user):
        return True
    return active_role_assignments(user).filter(
        scope=RoleScope.PROVINCE, province_id=province_id
    ).exists()


# ---------------------------------------------------------------------------
# Autorité PASTORALE (dimension orthogonale à RoleAssignment)
# ---------------------------------------------------------------------------

# Rôles pastoraux dont la charge porte une autorité TERRITORIALE. Le religieux et
# le fidèle n'en portent aucune : ils n'organisent ni ne publient (matrice §16).
# Plafond absolu de la voie pastorale — aucun appelant ne peut l'élargir.
PASTORAL_TERRITORIAL_ROLES = frozenset({
    PastoralRole.DIACRE,
    PastoralRole.PRETRE,
    PastoralRole.EVEQUE,
    PastoralRole.ARCHEVEQUE,
})

# Rôles dont l'autorité pastorale déborde la paroisse.
_PASTORAL_DIOCESAN_ROLES = frozenset({PastoralRole.EVEQUE, PastoralRole.ARCHEVEQUE})


def _pastoral_diocese_ids(user, *, membership_diocese_ids: set[int]) -> set[int]:
    """Diocèses couverts par le rôle PASTORAL : l'évêque couvre le sien,
    l'archevêque toute sa province. Dérivé de SON rattachement, jamais d'une
    donnée du client.

    On part des diocèses issus des appartenances (requête fraîche) plutôt que du
    seul ``user.diocese_id`` : cette colonne est dénormalisée par signal via
    ``.update()``, donc une instance ``BaseUser`` déjà chargée peut la porter
    périmée. Elle reste prise en compte, en complément.
    """
    role = getattr(user, "pastoral_role", None)
    if role not in _PASTORAL_DIOCESAN_ROLES:
        return set()

    diocese_ids = set(membership_diocese_ids)
    if user.diocese_id:
        diocese_ids.add(user.diocese_id)

    if role == PastoralRole.ARCHEVEQUE:
        province_ids = {
            pid
            for pid in Diocese.objects.filter(id__in=diocese_ids).values_list(
                "province_id", flat=True
            )
            if pid is not None
        }
        if user.province_id:
            province_ids.add(user.province_id)
        if province_ids:
            diocese_ids |= set(
                Diocese.objects.filter(province_id__in=province_ids).values_list("id", flat=True)
            )
    return diocese_ids


def user_has_pastoral_authority(
    *,
    user,
    scope_type: str,
    scope_parish_id: int | None = None,
    scope_diocese_id: int | None = None,
    scope_church_id: int | None = None,
    allowed_roles: frozenset = PASTORAL_TERRITORIAL_ROLES,
) -> bool:
    """Autorité issue du rôle PASTORAL, orthogonale à la dimension administrative
    (``UserRole`` / ``RoleAssignment``).

    Motivation : un curé validé porte ``pastoral_role=PRETRE`` sans forcément de
    capacité administrative (cf. ``services_clergy._resolve_capacity`` : « sans
    cible exploitable, aucune affectation scopée n'est créée »). Il reste pourtant
    l'acteur naturel des actes de SA paroisse — événement d'agenda comme réflexion
    pastorale. Sans cette voie, ``user_can_admin_parish`` lui refusait sa propre
    paroisse. Les appelants combinent donc les deux voies : **l'une suffit**.

    ``allowed_roles`` restreint la voie aux rôles que l'ACTE concerne (matrice
    §16) : l'agenda admet le diacre (il organise un événement), la réflexion
    pastorale ne l'admet pas (il ne publie pas). L'ensemble est TOUJOURS intersecté
    avec ``PASTORAL_TERRITORIAL_ROLES`` : aucun appelant ne peut ouvrir cette voie
    au religieux ni au fidèle, même en le demandant explicitement.

    FAIL-CLOSED : la portée demandée doit tomber dans le territoire d'appartenance
    RÉEL de l'utilisateur (``Membership`` → ``get_scope_ids``, diocèse/province
    dérivés). Un identifiant arbitraire venu du client n'ouvre jamais de droit, et
    la portée GLOBAL n'est JAMAIS accordée par cette voie — elle reste réservée aux
    administrateurs province / national.

    ``scope_type`` emploie le vocabulaire partagé (``SCOPE_*``), dont les valeurs
    sont celles des ``ScopeType`` de chaque modèle scopé (Event, PastoralReflection).
    """
    role = getattr(user, "pastoral_role", None)
    if role not in (frozenset(allowed_roles) & PASTORAL_TERRITORIAL_ROLES):
        return False

    scope = user.get_scope_ids()
    parish_ids = set(scope["parish_ids"])
    church_ids = set(scope["church_ids"])
    diocese_ids = _pastoral_diocese_ids(
        user, membership_diocese_ids=set(scope["diocese_ids"])
    )

    if scope_type == SCOPE_PARISH:
        if scope_parish_id is None:
            return False
        if scope_parish_id in parish_ids:
            return True
        return bool(diocese_ids) and Parish.objects.filter(
            pk=scope_parish_id, diocese_id__in=diocese_ids
        ).exists()

    if scope_type == SCOPE_CHURCH:
        if scope_church_id is None:
            return False
        if scope_church_id in church_ids:
            return True
        # Toute église de sa paroisse (curé) ou de son diocèse (évêque).
        qs = Church.objects.filter(pk=scope_church_id)
        if parish_ids and qs.filter(parish_id__in=parish_ids).exists():
            return True
        return bool(diocese_ids) and qs.filter(parish__diocese_id__in=diocese_ids).exists()

    if scope_type == SCOPE_DIOCESE:
        return scope_diocese_id is not None and scope_diocese_id in diocese_ids

    # GLOBAL : réservé aux administrateurs province / national.
    return False


# ---------------------------------------------------------------------------
# Clergé d'un territoire & chaîne de supériorité
# ---------------------------------------------------------------------------

def parish_principal_cure(parish_id: int) -> BaseUser | None:
    ra = (
        RoleAssignment.objects.filter(
            parish_id=parish_id,
            scope=RoleScope.PARISH,
            is_principal=True,
            is_active=True,
        )
        .select_related("user")
        .first()
    )
    return ra.user if ra else None


def clergy_of_parish(parish_id: int) -> QuerySet[BaseUser]:
    church_ids = list(Church.objects.filter(parish_id=parish_id).values_list("id", flat=True))
    user_ids = (
        RoleAssignment.objects.filter(is_active=True)
        .filter(
            Q(scope=RoleScope.PARISH, parish_id=parish_id)
            | Q(scope=RoleScope.CHURCH, church_id__in=church_ids)
        )
        .values_list("user_id", flat=True)
    )
    return BaseUser.objects.filter(id__in=set(user_ids))


def clergy_of_diocese(diocese_id: int) -> QuerySet[BaseUser]:
    parish_ids = list(Parish.objects.filter(diocese_id=diocese_id).values_list("id", flat=True))
    church_ids = list(
        Church.objects.filter(parish__diocese_id=diocese_id).values_list("id", flat=True)
    )
    user_ids = (
        RoleAssignment.objects.filter(is_active=True)
        .filter(
            Q(scope=RoleScope.DIOCESE, diocese_id=diocese_id)
            | Q(scope=RoleScope.PARISH, parish_id__in=parish_ids)
            | Q(scope=RoleScope.CHURCH, church_id__in=church_ids)
        )
        .values_list("user_id", flat=True)
    )
    return BaseUser.objects.filter(id__in=set(user_ids))


def _primary_parish_id(user) -> int | None:
    try:
        return user.profile.primary_parish_id
    except Exception:
        return None


def _diocese_bishop(diocese_id: int) -> BaseUser | None:
    ra = (
        RoleAssignment.objects.filter(
            scope=RoleScope.DIOCESE, diocese_id=diocese_id, is_active=True
        )
        .select_related("user")
        .first()
    )
    if ra:
        return ra.user
    return BaseUser.objects.filter(
        pastoral_role=PastoralRole.EVEQUE, diocese_id=diocese_id
    ).first()


def _province_archbishop(province_id: int) -> BaseUser | None:
    ra = (
        RoleAssignment.objects.filter(
            scope=RoleScope.PROVINCE, province_id=province_id, is_active=True
        )
        .select_related("user")
        .first()
    )
    if ra:
        return ra.user
    return BaseUser.objects.filter(
        pastoral_role=PastoralRole.ARCHEVEQUE, province_id=province_id
    ).first()


def superior_of(user) -> BaseUser | None:
    """
    Supérieur hiérarchique :
    fidèle → curé principal de sa paroisse ;
    curé (parish-scope) → doyen du doyenné si défini, sinon évêque du diocèse ;
    évêque / diocese-scope → archevêque de la province ;
    archevêque / province-scope → aucun (None).
    """
    if not user or not getattr(user, "is_authenticated", False):
        return None

    ras = active_role_assignments(user)

    diocese_ra = ras.filter(scope=RoleScope.DIOCESE).select_related("diocese").first()
    if diocese_ra and diocese_ra.diocese is not None:
        return _province_archbishop(diocese_ra.diocese.province_id)

    if getattr(user, "pastoral_role", None) == PastoralRole.EVEQUE and user.province_id:
        return _province_archbishop(user.province_id)

    parish_ra = (
        ras.filter(scope=RoleScope.PARISH)
        .select_related("parish__deanery", "parish__diocese")
        .first()
    )
    if parish_ra and parish_ra.parish is not None:
        parish = parish_ra.parish
        deanery = parish.deanery
        if deanery is not None and deanery.dean_id:
            return deanery.dean
        return _diocese_bishop(parish.diocese_id)

    primary_parish_id = _primary_parish_id(user)
    if primary_parish_id:
        cure = parish_principal_cure(primary_parish_id)
        if cure:
            return cure
        try:
            diocese_id = Parish.objects.values_list("diocese_id", flat=True).get(id=primary_parish_id)
            return _diocese_bishop(diocese_id)
        except Parish.DoesNotExist:
            return None
    return None
