"""Synchronisation des comptes dans les deux sens (docs/ADMIN-KEYCLOAK.md §4-5).

Application → Keycloak : les services d'administration (``services_admin``) écrivent dans
Keycloak dans la même transaction que la base (Keycloak en échec : rien n'est écrit côté
application, ou compensation). Les changements de profil faits par la personne sont poussés
par une tâche différée et réessayée (``account_push``).

Keycloak → application : les événements Keycloak (lus chaque minute par l'Admin REST API,
``keycloak_events_poll`` ; en option, reçus d'un SPI par webhook signé HMAC) déclenchent une
relecture du compte dans Keycloak (``account_pull``), qui fait foi pour l'identité (e-mail, nom, état,
e-mail vérifié, rôle ``platform_admin``). La réconciliation périodique (``keycloak_reconcile``)
rattrape tout le reste et produit un rapport.
"""

import hashlib
import hmac
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.authentication.keycloak_admin import KeycloakAdminError, KeycloakNotFoundError
from apps.integrations.keycloak import get_keycloak_admin
from apps.users.models import (
    BaseUser,
    KeycloakEvent,
    KeycloakEventStatus,
    KeycloakSyncCursor,
    KeycloakSyncRun,
    Profile,
)
from apps.users.services_privacy import ERASED_EMAIL_SUFFIX

logger = logging.getLogger(__name__)

# Écarts (``BaseUser.keycloak_sync_error`` et rapport)
ECART_KEYCLOAK_SEUL = "keycloak_seul"  # compte présent dans Keycloak seulement
ECART_APP_SEUL = "application_seule"  # compte non lié à Keycloak
ECART_SUPPRIME_KEYCLOAK = "supprime_dans_keycloak"  # lié, mais absent de Keycloak
ECART_CHAMPS = "champs_differents"
ECART_EMAIL_CONFLIT = "conflit_email"
ECART_OFFICES_EN_COURS = "supprime_avec_nominations"
ECART_SEUIL = "seuil_suppressions_depasse"


def _live_users() -> Any:
    return BaseUser.objects.exclude(email__endswith=ERASED_EMAIL_SUFFIX)


def _names(user: BaseUser) -> tuple[str, str]:
    profile = Profile.objects.filter(user=user).first()
    return (profile.first_name, profile.last_name) if profile else ("", "")


def keycloak_representation(
    user: BaseUser, *, first_name: str | None = None, last_name: str | None = None
) -> dict[str, Any]:
    first, last = _names(user)
    return {
        "username": user.email,
        "email": user.email,
        "firstName": first if first_name is None else first_name,
        "lastName": last if last_name is None else last_name,
        "enabled": bool(user.is_active),
        "emailVerified": bool(user.is_verified),
        "attributes": {"jangubi_id": [str(user.pk)]},
    }


# --- Keycloak → application ---------------------------------------------------------------


@dataclass
class ApplyResult:
    action: str  # cree | lie | mis_a_jour | inchange | efface | desactive | conflit
    user_id: str = ""
    fields: list[str] = field(default_factory=list)


def _diff(user: BaseUser, rep: dict[str, Any], platform_admin: bool | None) -> dict[str, Any]:
    first, last = _names(user)
    changes: dict[str, Any] = {}
    email = (rep.get("email") or "").strip().lower()
    if email and email != user.email:
        changes["email"] = email
    if bool(rep.get("enabled", True)) != user.is_active:
        changes["is_active"] = bool(rep.get("enabled", True))
    if bool(rep.get("emailVerified", False)) != user.is_verified:
        changes["is_verified"] = bool(rep.get("emailVerified", False))
    if (rep.get("firstName") or "") != first:
        changes["first_name"] = (rep.get("firstName") or "")[:50]
    if (rep.get("lastName") or "") != last:
        changes["last_name"] = (rep.get("lastName") or "")[:50]
    if platform_admin is not None and platform_admin != user.keycloak_platform_admin:
        changes["keycloak_platform_admin"] = platform_admin
    return changes


def _apply_changes(user: BaseUser, changes: dict[str, Any]) -> list[str]:
    applied: list[str] = []
    user_fields = [k for k in ("email", "is_active", "is_verified", "keycloak_platform_admin") if k in changes]
    if "email" in changes and BaseUser.objects.filter(email__iexact=changes["email"]).exclude(pk=user.pk).exists():
        user_fields.remove("email")
        user.keycloak_sync_error = ECART_EMAIL_CONFLIT
    else:
        user.keycloak_sync_error = ""
    for name in user_fields:
        setattr(user, name, changes[name])
        applied.append(name)
    user.keycloak_synced_at = timezone.now()
    user.save(update_fields=[*user_fields, "keycloak_synced_at", "keycloak_sync_error", "updated_at"])
    profile_fields = [k for k in ("first_name", "last_name") if k in changes]
    if profile_fields:
        profile, _ = Profile.objects.get_or_create(user=user)
        for name in profile_fields:
            setattr(profile, name, changes[name])
        profile.save(update_fields=[*profile_fields, "updated_at"])
        applied += profile_fields
    if "is_active" in applied or "keycloak_platform_admin" in applied:
        from apps.hierarchy import authz

        authz.invalidate_user(user.pk)
    return applied


def _erase_from_keycloak_deletion(user: BaseUser) -> ApplyResult:
    """Compte supprimé dans Keycloak : effacé côté application (RGPD), sauf nomination en cours
    (le compte est alors désactivé et signalé : l'autorité de nomination doit y mettre fin)."""
    from apps.users.services_privacy import account_erase, account_has_active_offices

    if account_has_active_offices(user):
        BaseUser.objects.filter(pk=user.pk).update(
            is_active=False, keycloak_sync_error=ECART_OFFICES_EN_COURS, keycloak_synced_at=timezone.now()
        )
        return ApplyResult("desactive", str(user.pk))
    account_erase(user=user, actor=None, action="compte.efface_keycloak")
    return ApplyResult("efface", str(user.pk))


def _platform_admin_of(client: Any, keycloak_id: str) -> bool | None:
    try:
        return settings.KEYCLOAK_PLATFORM_ADMIN_ROLE in client.user_realm_roles(keycloak_id)
    except KeycloakAdminError:
        return None


@transaction.atomic
def keycloak_user_apply(
    *, keycloak_id: str, rep: dict[str, Any] | None, platform_admin: bool | None = None
) -> ApplyResult:
    """Aligne l'application sur l'état Keycloak du compte ``keycloak_id`` (``rep`` absent :
    compte supprimé dans Keycloak). Idempotent."""
    user = BaseUser.objects.select_for_update().filter(keycloak_sub=keycloak_id).first()
    if rep is None:
        if user is None:
            return ApplyResult("inchange")
        return _erase_from_keycloak_deletion(user)
    if user is not None:
        applied = _apply_changes(user, _diff(user, rep, platform_admin))
        return ApplyResult("mis_a_jour" if applied else "inchange", str(user.pk), applied)
    email = (rep.get("email") or "").strip().lower()
    if not email:
        return ApplyResult("conflit")
    existing = BaseUser.objects.select_for_update().filter(email__iexact=email).first()
    if existing is not None:
        # Rattachement seulement d'un compte non lié et d'une adresse vérifiée dans Keycloak :
        # jamais de prise de compte par simple inscription.
        if existing.keycloak_sub or not rep.get("emailVerified"):
            BaseUser.objects.filter(pk=existing.pk).update(keycloak_sync_error=ECART_EMAIL_CONFLIT)
            return ApplyResult("conflit", str(existing.pk))
        existing.keycloak_sub = keycloak_id
        existing.save(update_fields=["keycloak_sub", "updated_at"])
        applied = _apply_changes(existing, _diff(existing, rep, platform_admin))
        return ApplyResult("lie", str(existing.pk), applied)
    try:
        with transaction.atomic():
            user = BaseUser.objects.create_user(
                email=email,
                phone_number=None,
                password=None,
                is_active=bool(rep.get("enabled", True)),
                is_verified=bool(rep.get("emailVerified", False)),
                keycloak_sub=keycloak_id,
            )
    except IntegrityError:
        return ApplyResult("conflit")
    Profile.objects.create(
        user=user, first_name=(rep.get("firstName") or "")[:50], last_name=(rep.get("lastName") or "")[:50]
    )
    BaseUser.objects.filter(pk=user.pk).update(
        keycloak_synced_at=timezone.now(), keycloak_platform_admin=bool(platform_admin)
    )
    return ApplyResult("cree", str(user.pk))


def account_pull(*, keycloak_id: str, client: Any = None) -> ApplyResult:
    """Relit le compte dans Keycloak et l'applique. Keycloak injoignable : l'erreur remonte
    (la tâche réessaie)."""
    client = client or get_keycloak_admin()
    try:
        rep = client.user_get(keycloak_id)
    except KeycloakNotFoundError:
        rep = None
    platform_admin = _platform_admin_of(client, keycloak_id) if rep is not None else None
    return keycloak_user_apply(keycloak_id=keycloak_id, rep=rep, platform_admin=platform_admin)


# --- Application → Keycloak ---------------------------------------------------------------


def account_push(*, user: BaseUser, client: Any = None) -> str:
    """Pousse l'identité de l'application vers Keycloak (compte lié) ou crée le compte Keycloak
    (compte non lié). Idempotent. Renvoie ``mis_a_jour``, ``cree``, ``lie`` ou ``ignore``."""
    if not settings.KEYCLOAK_ENABLED or user.email.endswith(ERASED_EMAIL_SUFFIX):
        return "ignore"
    client = client or get_keycloak_admin()
    rep = keycloak_representation(user)
    if user.keycloak_sub:
        try:
            client.user_update(
                user.keycloak_sub,
                {k: rep[k] for k in ("email", "firstName", "lastName", "enabled")},
            )
        except KeycloakNotFoundError:
            BaseUser.objects.filter(pk=user.pk).update(keycloak_sync_error=ECART_SUPPRIME_KEYCLOAK)
            return "absent"
        BaseUser.objects.filter(pk=user.pk).update(keycloak_synced_at=timezone.now(), keycloak_sync_error="")
        return "mis_a_jour"
    rep["requiredActions"] = ["UPDATE_PASSWORD"]
    keycloak_id, created = client.user_create(rep)
    updated = BaseUser.objects.filter(pk=user.pk, keycloak_sub__isnull=True).update(
        keycloak_sub=keycloak_id, keycloak_synced_at=timezone.now(), keycloak_sync_error=""
    )
    if not updated and created:
        client.user_delete(keycloak_id)  # compensation : lié entre-temps ailleurs
        return "ignore"
    return "cree" if created else "lie"


# --- Webhook (SPI d'événements) -----------------------------------------------------------

# Événements utilisateur (« access. ») qui changent l'identité ; les connexions sont ignorées.
USER_EVENT_TYPES = frozenset(
    {"REGISTER", "UPDATE_EMAIL", "VERIFY_EMAIL", "UPDATE_PROFILE", "DELETE_ACCOUNT", "UPDATE_TOTP", "REMOVE_TOTP"}
)
ADMIN_RESOURCE_TYPES = frozenset({"USER", "REALM_ROLE_MAPPING", "GROUP_MEMBERSHIP"})


def webhook_signature_valid(*, body: bytes, signature: str) -> bool:
    secret = settings.KEYCLOAK_WEBHOOK_SECRET
    if not secret or not signature:
        return False
    signature = signature.strip()
    if signature.lower().startswith("sha256="):
        signature = signature[7:]
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def _event_user_id(payload: dict[str, Any]) -> tuple[str, str]:
    """(type normalisé, identifiant Keycloak du compte) ; identifiant vide = événement ignoré."""
    raw_type = str(payload.get("type") or "")
    resource_path = str(payload.get("resourcePath") or "")
    if raw_type.startswith("admin.") or resource_path:
        resource_type = str(payload.get("resourceType") or raw_type.removeprefix("admin.").split("-", 1)[0])
        if resource_type not in ADMIN_RESOURCE_TYPES and not resource_path.startswith("users/"):
            return raw_type, ""
        parts = resource_path.split("/")
        return raw_type, parts[1] if len(parts) > 1 and parts[0] == "users" else ""
    name = raw_type.removeprefix("access.")
    if name not in USER_EVENT_TYPES:
        return raw_type, ""
    return raw_type, str(payload.get("userId") or "")


def keycloak_event_ingest(*, payload: dict[str, Any], defer: bool = True) -> tuple[KeycloakEvent, bool]:
    """Enregistre l'événement (idempotent sur ``uid``) ; renvoie ``(événement, nouveau)``.
    Le traitement est différé après validation de la transaction."""
    uid = str(payload.get("uid") or payload.get("id") or "")
    event_type, user_id = _event_user_id(payload)
    if not uid:
        digest = hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()
        uid = f"sans-uid-{digest[:40]}"
    event, created = KeycloakEvent.objects.get_or_create(
        uid=uid[:128],
        defaults={
            "event_type": event_type[:80],
            "keycloak_user_id": user_id[:64],
            "status": KeycloakEventStatus.RECU if user_id else KeycloakEventStatus.IGNORE,
        },
    )
    if created and user_id and defer:
        from apps.users.tasks import keycloak_event_process_task

        transaction.on_commit(lambda: keycloak_event_process_task.delay(event.pk))
    return event, created


def keycloak_event_process(*, event_id: int, client: Any = None) -> str:
    event = KeycloakEvent.objects.filter(pk=event_id).first()
    if event is None or event.status in (KeycloakEventStatus.TRAITE, KeycloakEventStatus.IGNORE):
        return "ignore"
    KeycloakEvent.objects.filter(pk=event_id).update(attempts=event.attempts + 1)
    try:
        result = account_pull(keycloak_id=event.keycloak_user_id, client=client)
    except KeycloakAdminError:
        KeycloakEvent.objects.filter(pk=event_id).update(
            status=KeycloakEventStatus.ECHEC, result="keycloak_injoignable"
        )
        raise
    KeycloakEvent.objects.filter(pk=event_id).update(
        status=KeycloakEventStatus.TRAITE, result=result.action, processed_at=timezone.now()
    )
    return result.action


# --- Lecture des événements par l'Admin REST API (sans SPI) --------------------------------

EVENTS_PAGE_SIZE = 100
EVENTS_OVERLAP_MS = 60_000  # relecture d'une minute : horloges, événements écrits en retard
FAILED_EVENTS_MAX_ATTEMPTS = 10


def _normalize_user_event(e: dict[str, Any]) -> dict[str, Any]:
    uid = e.get("id") or f"u-{e.get('time')}-{e.get('type')}-{e.get('userId')}"
    return {"uid": f"kc-{uid}", "type": f"access.{e.get('type', '')}", "userId": e.get("userId") or ""}


def _normalize_admin_event(e: dict[str, Any]) -> dict[str, Any]:
    resource_type = str(e.get("resourceType") or "")
    operation = str(e.get("operationType") or "")
    path = str(e.get("resourcePath") or "")
    uid = e.get("id") or f"a-{e.get('time')}-{operation}-{path}"
    return {
        "uid": f"kc-{uid}",
        "type": f"admin.{resource_type}-{operation}",
        "resourceType": resource_type,
        "resourcePath": path,
    }


def _fetch_since(fetch: Any, floor_ms: int, limit: int) -> list[dict[str, Any]]:
    """Événements d'horodatage ≥ ``floor_ms`` (Keycloak les renvoie du plus récent au plus ancien)."""
    import datetime

    date_from = datetime.datetime.fromtimestamp(floor_ms / 1000, tz=datetime.UTC).date().isoformat()
    collected: list[dict[str, Any]] = []
    first = 0
    while len(collected) < limit:
        page = fetch(date_from=date_from, first=first, max_results=EVENTS_PAGE_SIZE)
        fresh = [e for e in page if int(e.get("time") or 0) >= floor_ms]
        collected += fresh
        if len(page) < EVENTS_PAGE_SIZE or len(fresh) < len(page):
            break
        first += EVENTS_PAGE_SIZE
    return sorted(collected[:limit], key=lambda e: int(e.get("time") or 0))


def _process_pending(client: Any, counts: dict[str, int], done: dict[str, str]) -> None:
    """Traite les événements reçus (ou en échec, dans la limite des tentatives), un seul
    relecture par compte et par passe."""
    pending = (
        KeycloakEvent.objects.filter(
            status__in=[KeycloakEventStatus.RECU, KeycloakEventStatus.ECHEC], attempts__lt=FAILED_EVENTS_MAX_ATTEMPTS
        )
        .exclude(keycloak_user_id="")
        .order_by("received_at", "pk")
    )
    for event in pending:
        user_id = event.keycloak_user_id
        if user_id in done:
            KeycloakEvent.objects.filter(pk=event.pk).update(
                status=KeycloakEventStatus.TRAITE, result=done[user_id], processed_at=timezone.now()
            )
            counts["traites"] += 1
            continue
        try:
            done[user_id] = keycloak_event_process(event_id=event.pk, client=client)
            counts["traites"] += 1
        except KeycloakAdminError:
            counts["echecs"] += 1


def keycloak_events_poll(*, client: Any = None) -> dict[str, int]:
    """Lit les nouveaux événements utilisateur et d'administration depuis le curseur, les
    enregistre (dédoublonnés sur leur identifiant) et aligne les comptes concernés. Un flux
    injoignable garde son curseur : il sera relu à la passe suivante."""
    if not settings.KEYCLOAK_ENABLED or not settings.KEYCLOAK_EVENTS_POLL_ENABLED:
        return {}
    client = client or get_keycloak_admin()
    counts = {"lus": 0, "nouveaux": 0, "traites": 0, "echecs": 0}
    now_ms = int(timezone.now().timestamp() * 1000)
    lookback_ms = settings.KEYCLOAK_EVENTS_INITIAL_LOOKBACK_HOURS * 3600 * 1000
    streams = (
        ("utilisateur", client.events, _normalize_user_event),
        ("admin", client.admin_events, _normalize_admin_event),
    )
    for name, fetch, normalize in streams:
        cursor, _ = KeycloakSyncCursor.objects.get_or_create(name=name)
        floor = cursor.last_event_ms - EVENTS_OVERLAP_MS if cursor.last_event_ms else now_ms - lookback_ms
        try:
            events = _fetch_since(fetch, floor, settings.KEYCLOAK_EVENTS_MAX_PER_POLL)
        except KeycloakAdminError as exc:
            cursor.last_error = str(exc)[:255]
            cursor.last_polled_at = timezone.now()
            cursor.save(update_fields=["last_error", "last_polled_at"])
            counts["echecs"] += 1
            continue
        latest = cursor.last_event_ms
        for raw in events:
            counts["lus"] += 1
            _, created = keycloak_event_ingest(payload=normalize(raw), defer=False)
            counts["nouveaux"] += int(created)
            latest = max(latest, int(raw.get("time") or 0))
        cursor.last_event_ms = latest
        cursor.last_polled_at = timezone.now()
        cursor.last_error = ""
        cursor.save(update_fields=["last_event_ms", "last_polled_at", "last_error"])
    _process_pending(client, counts, {})
    return counts


# --- Réconciliation -----------------------------------------------------------------------


@dataclass
class Ecart:
    kind: str
    keycloak_id: str = ""
    user_id: str = ""
    email: str = ""
    fields: list[str] = field(default_factory=list)
    correction: str = ""  # action réalisée (ou prévue en simulation)


REPORT_MAX_ITEMS = 500


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}***@{domain}" if domain else email


def keycloak_reconcile(
    *, dry_run: bool = True, trigger: str = "tache", actor: Any = None, client: Any = None
) -> KeycloakSyncRun:
    """Compare les deux annuaires, corrige les écarts (sauf ``dry_run``) et archive le rapport.
    Keycloak fait foi pour l'identité ; un compte de l'application non lié est créé dans
    Keycloak ; un compte lié absent de Keycloak (absence confirmée compte par compte) est effacé,
    dans la limite de ``KEYCLOAK_RECONCILE_MAX_DELETIONS``."""
    run = KeycloakSyncRun.objects.create(
        dry_run=dry_run, trigger=trigger, triggered_by=actor if getattr(actor, "is_authenticated", False) else None
    )
    ecarts: list[Ecart] = []
    errors = 0
    try:
        if not settings.KEYCLOAK_ENABLED:
            raise KeycloakAdminError("Synchronisation Keycloak désactivée (KEYCLOAK_ENABLED).")
        client = client or get_keycloak_admin()
        kc_users = {str(u["id"]): u for u in client.users_list()}
        platform_admins = set(client.role_members(settings.KEYCLOAK_PLATFORM_ADMIN_ROLE))
    except KeycloakAdminError as exc:
        run.error = str(exc)[:255]
        run.finished_at = timezone.now()
        run.save(update_fields=["error", "finished_at"])
        logger.warning("keycloak.reconcile.unavailable", extra={"error_type": type(exc).__name__})
        return run

    linked = {u.keycloak_sub: u for u in _live_users().filter(keycloak_sub__isnull=False).select_related("profile")}

    # 1. Comptes Keycloak : présents des deux côtés (champs) ou Keycloak seul.
    for keycloak_id, rep in kc_users.items():
        is_admin = keycloak_id in platform_admins
        # JB-WEB-037/043 : un platform_admin doit avoir un second facteur (comme le staff).
        # S'il n'a pas encore d'OTP, on exige sa configuration à la prochaine connexion.
        # Idempotent (l'action n'est posée qu'une fois) : ne crée aucun écart.
        if is_admin and not dry_run and not rep.get("totp"):
            if "CONFIGURE_TOTP" not in (rep.get("requiredActions") or []):
                try:
                    client.add_required_action(keycloak_id, "CONFIGURE_TOTP")
                except KeycloakAdminError:
                    logger.warning("keycloak.reconcile.totp_action_failed")
        user = linked.get(keycloak_id)
        if user is not None:
            changes = _diff(user, rep, is_admin)
            if not changes:
                continue
            ecart = Ecart(
                ECART_CHAMPS, keycloak_id, str(user.pk), _mask(user.email), sorted(changes), "aligner_sur_keycloak"
            )
        else:
            ecart = Ecart(ECART_KEYCLOAK_SEUL, keycloak_id, "", _mask(rep.get("email") or ""), [], "lier_ou_creer")
        if not dry_run:
            try:
                result = keycloak_user_apply(keycloak_id=keycloak_id, rep=rep, platform_admin=is_admin)
                ecart.correction = result.action
                ecart.user_id = ecart.user_id or result.user_id
            except Exception:  # noqa: BLE001 — un compte en échec ne bloque pas la passe
                logger.exception("keycloak.reconcile.apply_failed")
                ecart.correction = "echec"
                errors += 1
        ecarts.append(ecart)

    # 2. Comptes liés absents de Keycloak : absence confirmée puis effacement (avec seuil).
    missing = [u for sub, u in linked.items() if sub not in kc_users]
    confirmed: list[BaseUser] = []
    for user in missing:
        try:
            still_there = client.user_find(user.keycloak_sub) is not None
        except KeycloakAdminError:
            errors += 1
            continue
        if not still_there:
            confirmed.append(user)
    over_threshold = len(confirmed) > settings.KEYCLOAK_RECONCILE_MAX_DELETIONS
    for user in confirmed:
        ecart = Ecart(ECART_SUPPRIME_KEYCLOAK, user.keycloak_sub or "", str(user.pk), _mask(user.email), [], "effacer")
        if over_threshold:
            ecart.correction = ECART_SEUIL
            if not dry_run:
                BaseUser.objects.filter(pk=user.pk).update(keycloak_sync_error=ECART_SUPPRIME_KEYCLOAK)
        elif not dry_run:
            try:
                ecart.correction = keycloak_user_apply(keycloak_id=user.keycloak_sub or "", rep=None).action
            except Exception:  # noqa: BLE001
                logger.exception("keycloak.reconcile.erase_failed")
                ecart.correction = "echec"
                errors += 1
        ecarts.append(ecart)

    # 3. Comptes de l'application non liés : créés (ou rattachés) dans Keycloak.
    for user in _live_users().filter(keycloak_sub__isnull=True):
        ecart = Ecart(ECART_APP_SEUL, "", str(user.pk), _mask(user.email), [], "creer_dans_keycloak")
        if not dry_run:
            try:
                ecart.correction = account_push(user=user, client=client)
            except KeycloakAdminError:
                BaseUser.objects.filter(pk=user.pk).update(keycloak_sync_error=ECART_APP_SEUL)
                ecart.correction = "echec"
                errors += 1
        ecarts.append(ecart)

    counts: dict[str, int] = {"keycloak": len(kc_users), "application": len(linked), "erreurs": errors}
    for ecart in ecarts:
        counts[ecart.kind] = counts.get(ecart.kind, 0) + 1
    counts["ecarts"] = len(ecarts)
    run.counts = counts
    run.report = [asdict(e) for e in ecarts[:REPORT_MAX_ITEMS]]
    run.success = errors == 0
    run.finished_at = timezone.now()
    run.save(update_fields=["counts", "report", "success", "finished_at"])
    return run


def sync_pending_q() -> Q:
    """Comptes en écart connu : non liés, ou signalés par la dernière synchronisation."""
    return Q(keycloak_sub__isnull=True) | ~Q(keycloak_sync_error="")
