"""Lectures de l'administration des comptes (docs/ADMIN-KEYCLOAK.md) : liste, fiche, journal,
tableau de bord, état de la synchronisation, export. Toujours restreintes à la portée de l'acteur."""

import datetime
from typing import Any
from uuid import UUID

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.core.exceptions import NotFoundError
from apps.hierarchy.enums import StatutVerification
from apps.hierarchy.models import AuditEvent, Node, OfficeAssignment
from apps.users import scope_admin
from apps.users.models import BaseUser, KeycloakEvent, KeycloakEventStatus, KeycloakSyncCursor, KeycloakSyncRun
from apps.users.services_privacy import ERASED_EMAIL_SUFFIX

STATUS_ACTIF = "actif"
STATUS_DESACTIVE = "desactive"
STATUS_EN_ATTENTE = "en_attente"  # e-mail non vérifié, ou état de vie en attente de validation
STATUSES = (STATUS_ACTIF, STATUS_DESACTIVE, STATUS_EN_ATTENTE)

SYNC_OK = "synchronise"
SYNC_NON_LIE = "non_lie"
SYNC_ECART = "ecart"
SYNC_STATES = (SYNC_OK, SYNC_NON_LIE, SYNC_ECART)

ROLE_PLATFORM_ADMIN = "platform_admin"
ROLE_STAFF = "staff"
ROLE_FIDELE = "fidele"
ROLES = (ROLE_FIDELE, ROLE_STAFF, ROLE_PLATFORM_ADMIN)

ORDERINGS = {
    "recent": ("-created_at", "pk"),
    "ancien": ("created_at", "pk"),
    "email": ("email", "pk"),
    "nom": ("profile__last_name", "profile__first_name", "pk"),
}
PENDING_STATUTS = (StatutVerification.DECLARE, StatutVerification.COMPLEMENT)


def _office_exists() -> Exists:
    today = timezone.localdate()
    return Exists(
        OfficeAssignment.objects.filter(person=OuterRef("pk"), status="active", start_date__lte=today).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=today)
        )
    )


def _pending_q() -> Q:
    return Q(is_verified=False) | (~Q(etat_de_vie="laic") & Q(statut_verification__in=PENDING_STATUTS))


def _base(actor: Any) -> QuerySet[BaseUser]:
    return (
        BaseUser.objects.exclude(email__endswith=ERASED_EMAIL_SUFFIX)
        .filter(scope_admin.scope_q(actor))
        .select_related("profile", "admin_node")
        .annotate(has_office=_office_exists())
    )


def admin_account_list(*, actor: Any, filters: dict[str, Any]) -> QuerySet[BaseUser]:
    qs = _base(actor)
    q = (filters.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(email__icontains=q)
            | Q(profile__first_name__icontains=q)
            | Q(profile__last_name__icontains=q)
            | Q(phone_number__icontains=q)
        )
    status = filters.get("status")
    if status == STATUS_DESACTIVE:
        qs = qs.filter(is_active=False)
    elif status == STATUS_EN_ATTENTE:
        qs = qs.filter(is_active=True).filter(_pending_q())
    elif status == STATUS_ACTIF:
        qs = qs.filter(is_active=True).exclude(_pending_q())
    role = filters.get("role")
    if role == ROLE_PLATFORM_ADMIN:
        qs = qs.filter(keycloak_platform_admin=True)
    elif role == ROLE_STAFF:
        qs = qs.filter(_office_exists())
    elif role == ROLE_FIDELE:
        qs = qs.exclude(_office_exists()).filter(keycloak_platform_admin=False)
    sync = filters.get("sync")
    if sync == SYNC_NON_LIE:
        qs = qs.filter(keycloak_sub__isnull=True)
    elif sync == SYNC_ECART:
        qs = qs.exclude(keycloak_sync_error="")
    elif sync == SYNC_OK:
        qs = qs.filter(keycloak_sub__isnull=False, keycloak_sync_error="")
    if etat := filters.get("etat_de_vie"):
        qs = qs.filter(etat_de_vie=etat)
    if node_id := filters.get("node"):
        node = Node.objects.filter(pk=node_id).first()
        if node is None:
            return qs.none()
        qs = qs.filter(
            Q(admin_node__path__startswith=node.path)
            | Q(
                pk__in=OfficeAssignment.objects.filter(
                    node__path__startswith=node.path, status__in=scope_admin.OPEN_STATUSES
                ).values("person_id")
            )
        )
    if created_from := filters.get("created_from"):
        qs = qs.filter(created_at__date__gte=created_from)
    if created_to := filters.get("created_to"):
        qs = qs.filter(created_at__date__lte=created_to)
    return qs.order_by(*ORDERINGS.get(filters.get("ordering") or "recent", ORDERINGS["recent"]))


def admin_account_get(*, actor: Any, account_id: UUID | str) -> BaseUser:
    """Compte visible par l'acteur (404 sinon : on ne révèle pas l'existence d'un compte hors portée)."""
    account = _base(actor).filter(pk=account_id).first()
    if account is None:
        raise NotFoundError("Compte introuvable.", {"account_id": str(account_id)})
    return account


def _full_name(user: BaseUser) -> tuple[str, str]:
    profile = getattr(user, "profile", None)
    return (profile.first_name, profile.last_name) if profile else ("", "")


def account_status(user: BaseUser) -> str:
    if not user.is_active:
        return STATUS_DESACTIVE
    pending = not user.is_verified or (user.etat_de_vie != "laic" and user.statut_verification in PENDING_STATUTS)
    return STATUS_EN_ATTENTE if pending else STATUS_ACTIF


def sync_state(user: BaseUser) -> str:
    if not user.keycloak_sub:
        return SYNC_NON_LIE
    return SYNC_ECART if user.keycloak_sync_error else SYNC_OK


def account_role(user: BaseUser) -> str:
    if user.keycloak_platform_admin:
        return ROLE_PLATFORM_ADMIN
    return ROLE_STAFF if getattr(user, "has_office", False) else ROLE_FIDELE


def admin_account_row(*, actor: Any, user: BaseUser) -> dict[str, Any]:
    first, last = _full_name(user)
    return {
        "id": user.pk,
        "email": user.email,
        "first_name": first,
        "last_name": last,
        "full_name": f"{first} {last}".strip(),
        "phone_number": str(user.phone_number) if user.phone_number else None,
        "status": account_status(user),
        "role": account_role(user),
        "etat_de_vie": user.etat_de_vie,
        "email_verified": bool(user.is_verified),
        "keycloak_id": user.keycloak_sub,
        "sync": sync_state(user),
        "sync_error": user.keycloak_sync_error or None,
        "synced_at": user.keycloak_synced_at,
        "admin_node": {"id": user.admin_node.pk, "name": user.admin_node.name} if user.admin_node else None,
        "created_at": user.created_at,
        "last_login": user.last_login,
        "last_seen_on": user.last_seen_on,
        "can_manage": scope_admin.can_manage(actor, user),
    }


def _offices(user: BaseUser) -> list[dict[str, Any]]:
    return [
        {
            "id": a.pk,
            "office": a.office_type.code,
            "office_label": a.title,
            "node": {"id": a.node.pk, "name": a.node.name},
            "status": a.status,
            "start_date": a.start_date,
            "end_date": a.end_date,
        }
        for a in OfficeAssignment.objects.filter(person=user, status__in=scope_admin.OPEN_STATUSES)
        .select_related("node", "office_type")
        .order_by("start_date")
    ]


def admin_account_detail(*, actor: Any, user: BaseUser, keycloak: dict[str, Any] | None) -> dict[str, Any]:
    return {
        **admin_account_row(actor=actor, user=user),
        "statut_verification": user.statut_verification,
        "degre_ordre": user.degre_ordre,
        "offices": _offices(user),
        "scope_nodes": [{"id": n.pk, "name": n.name} for n in scope_admin.account_scope_nodes(user)],
        "keycloak": keycloak,
    }


def keycloak_account_state(*, user: BaseUser) -> dict[str, Any] | None:
    """État en direct dans Keycloak (compte, second facteur, sessions, rôles, groupes, blocage).
    ``None`` si le compte n'est pas lié ; ``{"available": False}`` si Keycloak est injoignable."""
    from django.conf import settings

    from apps.authentication.keycloak_admin import KeycloakAdminError, KeycloakNotFoundError
    from apps.integrations.keycloak import get_keycloak_admin

    if not user.keycloak_sub:
        return None
    if not settings.KEYCLOAK_ENABLED:
        return {"available": False}
    client = get_keycloak_admin()
    try:
        rep = client.user_get(user.keycloak_sub)
        credentials = client.user_credentials(user.keycloak_sub)
        sessions = client.user_sessions(user.keycloak_sub)
        roles = sorted(client.user_realm_roles(user.keycloak_sub))
        groups = sorted(g.get("path") or g.get("name") or "" for g in client.user_groups(user.keycloak_sub))
        brute = client.brute_force_status(user.keycloak_sub)
    except KeycloakNotFoundError:
        return {"available": True, "exists": False}
    except KeycloakAdminError:
        return {"available": False}
    types = {c.get("type") for c in credentials}
    return {
        "available": True,
        "exists": True,
        "enabled": bool(rep.get("enabled", True)),
        "email_verified": bool(rep.get("emailVerified", False)),
        "required_actions": list(rep.get("requiredActions") or []),
        "otp": bool(types & {"otp", "totp"}),
        "webauthn": bool(types & {"webauthn", "webauthn-passwordless"}),
        "password": "password" in types,
        "realm_roles": roles,
        "groups": groups,
        "locked_by_brute_force": bool(brute.get("disabled", False)),
        "failed_logins": int(brute.get("numFailures", 0) or 0),
        "sessions": [
            {
                "id": str(s.get("id", "")),
                "ip": s.get("ipAddress") or None,
                "started_at": _ms(s.get("start")),
                "last_access": _ms(s.get("lastAccess")),
                "clients": sorted(str(c) for c in (s.get("clients") or {}).values()),
            }
            for s in sessions
        ],
    }


def _ms(value: Any) -> datetime.datetime | None:
    if value in (None, ""):
        return None
    return datetime.datetime.fromtimestamp(int(value) / 1000, tz=datetime.UTC)


# --- Journal d'audit ------------------------------------------------------------------------


def admin_audit_list(*, actor: Any, filters: dict[str, Any]) -> QuerySet[AuditEvent]:
    """Actions sur les comptes (``compte.*``) : tout pour la plateforme, sinon le périmètre."""
    qs = AuditEvent.objects.filter(action__startswith="compte.").select_related("actor", "node")
    if not scope_admin.is_platform(actor):
        qs = qs.filter(node__in=scope_admin.managed_nodes(actor))
    if account_id := filters.get("account"):
        qs = qs.filter(target_type="users.BaseUser", target_id=str(account_id))
    if actor_id := filters.get("actor"):
        qs = qs.filter(actor_id=actor_id)
    if action := filters.get("action"):
        qs = qs.filter(action__startswith=action)
    if date_from := filters.get("date_from"):
        qs = qs.filter(at__date__gte=date_from)
    if date_to := filters.get("date_to"):
        qs = qs.filter(at__date__lte=date_to)
    return qs.order_by("-at")


def audit_targets(events: list[AuditEvent]) -> dict[str, str]:
    ids = [e.target_id for e in events if e.target_type == "users.BaseUser"]
    return {str(pk): email for pk, email in BaseUser.objects.filter(pk__in=ids).values_list("pk", "email")}


# --- Tableau de bord et synchronisation ---------------------------------------------------


def admin_dashboard(*, actor: Any) -> dict[str, Any]:
    qs = _base(actor)
    since = timezone.now() - datetime.timedelta(days=30)
    counts = qs.aggregate(
        total=Count("pk"),
        actifs=Count("pk", filter=Q(is_active=True) & ~_pending_q()),
        en_attente=Count("pk", filter=Q(is_active=True) & _pending_q()),
        desactives=Count("pk", filter=Q(is_active=False)),
        responsables=Count("pk", filter=Q(has_office=True)),
        administrateurs_plateforme=Count("pk", filter=Q(keycloak_platform_admin=True)),
        crees_30_jours=Count("pk", filter=Q(created_at__gte=since)),
        non_lies=Count("pk", filter=Q(keycloak_sub__isnull=True)),
        ecarts=Count("pk", filter=~Q(keycloak_sync_error="")),
    )
    from apps.invitations.models import ClergyInvitation, InvitationStatus

    invitations = ClergyInvitation.objects.filter(status=InvitationStatus.EN_ATTENTE, expires_at__gt=timezone.now())
    if not scope_admin.is_platform(actor):
        invitations = invitations.filter(node__in=scope_admin.managed_nodes(actor))
    counts["invitations_en_attente"] = invitations.count()
    last = KeycloakSyncRun.objects.filter(dry_run=False).first()
    return {
        "comptes": counts,
        "synchronisation": {
            "derniere_reconciliation": last.finished_at if last else None,
            "derniere_reconciliation_reussie": last.success if last else None,
            "ecarts_derniere_reconciliation": (last.counts or {}).get("ecarts", 0) if last else None,
        },
    }


def sync_status() -> dict[str, Any]:
    from django.conf import settings

    live = BaseUser.objects.exclude(email__endswith=ERASED_EMAIL_SUFFIX)
    runs = list(KeycloakSyncRun.objects.all()[:10])
    events = KeycloakEvent.objects.aggregate(
        recus=Count("pk", filter=Q(status=KeycloakEventStatus.RECU)),
        echecs=Count("pk", filter=Q(status=KeycloakEventStatus.ECHEC)),
        traites_24h=Count(
            "pk",
            filter=Q(
                status=KeycloakEventStatus.TRAITE, processed_at__gte=timezone.now() - datetime.timedelta(hours=24)
            ),
        ),
    )
    last_event = KeycloakEvent.objects.order_by("-received_at").values_list("received_at", flat=True).first()
    return {
        "enabled": bool(settings.KEYCLOAK_ENABLED),
        "events_polling": bool(settings.KEYCLOAK_EVENTS_POLL_ENABLED),
        "webhook_enabled": bool(settings.KEYCLOAK_WEBHOOK_ENABLED and settings.KEYCLOAK_WEBHOOK_SECRET),
        "curseurs": [
            {
                "name": c.name,
                "last_event_at": _ms(c.last_event_ms) if c.last_event_ms else None,
                "last_polled_at": c.last_polled_at,
                "last_error": c.last_error or None,
            }
            for c in KeycloakSyncCursor.objects.order_by("name")
        ],
        "comptes_non_lies": live.filter(keycloak_sub__isnull=True).count(),
        "comptes_en_ecart": live.exclude(keycloak_sync_error="").count(),
        "ecarts_par_type": dict(
            live.exclude(keycloak_sync_error="")
            .values_list("keycloak_sync_error")
            .annotate(n=Count("pk"))
            .values_list("keycloak_sync_error", "n")
        ),
        "evenements": {**events, "dernier_recu": last_event},
        "reconciliations": runs,
    }


def sync_run_get(*, run_id: int) -> KeycloakSyncRun:
    run = KeycloakSyncRun.objects.filter(pk=run_id).first()
    if run is None:
        raise NotFoundError("Réconciliation introuvable.", {"run_id": run_id})
    return run


# --- Export CSV -----------------------------------------------------------------------------

EXPORT_COLUMNS = (
    "id", "email", "prenom", "nom", "statut", "role", "etat_de_vie", "email_verifie", "lie_keycloak",
    "synchronisation", "noeud", "cree_le", "derniere_activite",
)  # fmt: skip


def _safe(value: Any) -> str:
    """Neutralise l'injection de formules dans un tableur (=, +, -, @)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def admin_export_rows(*, actor: Any, filters: dict[str, Any]) -> Any:
    yield EXPORT_COLUMNS
    for user in admin_account_list(actor=actor, filters=filters).iterator(chunk_size=500):
        first, last = _full_name(user)
        yield tuple(
            _safe(v)
            for v in (
                user.pk, user.email, first, last, account_status(user), account_role(user), user.etat_de_vie,
                "oui" if user.is_verified else "non", "oui" if user.keycloak_sub else "non", sync_state(user),
                user.admin_node.name if user.admin_node else "", user.created_at.date().isoformat(),
                user.last_seen_on.isoformat() if user.last_seen_on else "",
            )
        )  # fmt: skip
