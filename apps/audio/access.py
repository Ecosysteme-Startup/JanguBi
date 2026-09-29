"""Règles d'accès de la sonothèque, au-dessus de ``peut()`` (plan suite V2, §5.1 et §5.3).

- ``public`` : tout le monde, même sans compte ;
- ``paroisse`` : membres rattachés au nœud de la source, c'est-à-dire
  * les fidèles dont la paroisse suivie est ce nœud ou dans son sous-arbre,
  * les titulaires d'un office sur ce nœud, son sous-arbre, ou au-dessus (office hérité) ;
- ``prive`` : brouillon du staff, visible seulement de ceux qui ont ``audio.publier`` sur le nœud.

Le contexte d'appartenance d'un utilisateur est mis en cache 5 minutes (``AUDIO_AUTHZ_CACHE_SECONDS``).
"""

from dataclasses import dataclass
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audio.enums import TrackStatus, Visibility
from apps.audio.models import Album, AudioSource, Playlist, Track
from apps.core.exceptions import NotFoundError, PermissionDeniedError
from apps.hierarchy import authz
from apps.hierarchy.models import Node

STEPLEN = 4  # treebeard MP_Node : longueur d'un segment de chemin

PUBLISH = "audio.publier"
MODERATE = "audio.moderer"


@dataclass(frozen=True)
class Membership:
    """Ce qu'il faut savoir d'un utilisateur pour filtrer le catalogue."""

    user_id: Any
    member_paths: tuple[str, ...]  # paroisse suivie + nœuds de ses nominations actives
    grant_scopes: tuple[tuple[str, bool], ...]  # (chemin, hérite) de toutes ses nominations
    publish_scopes: tuple[tuple[str, bool], ...]  # (chemin, hérite) où il a audio.publier ("" = tout)

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None


ANONYMOUS = Membership(user_id=None, member_paths=(), grant_scopes=(), publish_scopes=())


def _membership_key(user_id: Any) -> str:
    return f"audio:membership:v1:{user_id}"


def membership(user: Any) -> Membership:
    if not getattr(user, "is_authenticated", False):
        return ANONYMOUS
    key = _membership_key(user.pk)
    cached = cache.get(key)
    if cached is not None:
        return cached
    grants = authz.grants(user)
    paths: list[str] = []
    followed = getattr(user, "paroisse_suivie", None)
    if followed is not None:
        paths.append(followed.path)
    paths += [g.path for g in grants if g.path]
    result = Membership(
        user_id=user.pk,
        member_paths=tuple(dict.fromkeys(paths)),
        grant_scopes=tuple(dict.fromkeys((g.path, g.inherits) for g in grants)),
        publish_scopes=tuple(dict.fromkeys((g.path, g.inherits) for g in grants if g.capability == PUBLISH)),
    )
    cache.set(key, result, settings.AUDIO_AUTHZ_CACHE_SECONDS)
    return result


def membership_invalidate(user_id: Any) -> None:
    cache.delete(_membership_key(user_id))


def _prefixes(path: str) -> list[str]:
    return [path[:i] for i in range(STEPLEN, len(path) + 1, STEPLEN)]


def _covers(scopes: tuple[tuple[str, bool], ...], path: str) -> bool:
    return any(path == p or (inherits and path.startswith(p)) for p, inherits in scopes)


def is_member(m: Membership, node: Node) -> bool:
    if m.is_anonymous:
        return False
    return any(p.startswith(node.path) for p in m.member_paths) or _covers(m.grant_scopes, node.path)


def can_publish(user: Any, node: Node) -> bool:
    return getattr(user, "is_authenticated", False) and authz.peut(user, PUBLISH, node)


def can_moderate(user: Any, node: Node) -> bool:
    return getattr(user, "is_authenticated", False) and authz.peut(user, MODERATE, node)


def require_publish(user: Any, node: Node) -> None:
    if not can_publish(user, node):
        raise PermissionDeniedError("Vous ne pouvez pas publier pour cette source.", code="audio_forbidden")
    authz.mfa_check(user)


def require_moderate(user: Any, node: Node) -> None:
    if not can_moderate(user, node):
        raise PermissionDeniedError("Vous ne pouvez pas modérer cette source.", code="audio_forbidden")
    authz.mfa_check(user)


def level_allowed(m: Membership, node: Node, visibility: str) -> bool:
    if visibility == Visibility.PUBLIC:
        return True
    if _covers(m.publish_scopes, node.path):
        return True
    return visibility == Visibility.PAROISSE and is_member(m, node)


def access_level(m: Membership, node: Node) -> str:
    """Niveau le plus fermé que ``m`` peut voir sur ``node`` : sert de clé au cache du catalogue."""
    if _covers(m.publish_scopes, node.path):
        return Visibility.PRIVE
    if is_member(m, node):
        return Visibility.PAROISSE
    return Visibility.PUBLIC


# --- Filtres de QuerySet ---------------------------------------------------------------------


def _visibility_q(m: Membership, *, field: str, node_path: str) -> Q:
    """Condition SQL « visible pour ``m`` » sur un champ de visibilité et le chemin du nœud."""
    condition = Q(**{field: Visibility.PUBLIC})
    if m.is_anonymous:
        return condition
    member_nodes = Q(**{f"{node_path}__in": sorted({p for mp in m.member_paths for p in _prefixes(mp)})})
    for path, inherits in m.grant_scopes:
        member_nodes |= Q(**{f"{node_path}__startswith": path}) if inherits else Q(**{node_path: path})
    condition |= Q(**{field: Visibility.PAROISSE}) & member_nodes
    for path, inherits in m.publish_scopes:
        condition |= Q(**{f"{node_path}__startswith": path}) if inherits else Q(**{node_path: path})
    return condition


def listenable_tracks(m: Membership) -> QuerySet[Track]:
    """Pistes du catalogue pour ``m`` : prêtes, publiées, non retirées, visibilité autorisée."""
    return Track.objects.filter(
        status=TrackStatus.PRET,
        published_at__isnull=False,
        published_at__lte=timezone.now(),
        hidden_at__isnull=True,
        source__is_active=True,
    ).filter(_visibility_q(m, field="effective_visibility", node_path="source__node__path"))


def visible_albums(m: Membership) -> QuerySet[Album]:
    return Album.objects.filter(
        published_at__isnull=False, published_at__lte=timezone.now(), source__is_active=True
    ).filter(_visibility_q(m, field="visibility", node_path="source__node__path"))


def visible_editorial_playlists(m: Membership) -> QuerySet[Playlist]:
    return Playlist.objects.filter(source__isnull=False, published_at__isnull=False, source__is_active=True).filter(
        _visibility_q(m, field="visibility", node_path="source__node__path")
    )


def visible_sources() -> QuerySet[AudioSource]:
    """Les sources elles-mêmes sont publiques (nom, type, paroisse) : leur contenu est filtré."""
    return AudioSource.objects.filter(is_active=True)


# --- Décisions unitaires (lecture) -----------------------------------------------------------


def track_decision_key(user_id: Any, track: Track) -> str:
    stamp = int(track.updated_at.timestamp() * 1000) if track.updated_at else 0
    return f"audio:play-authz:{user_id or 'anon'}:{track.pk}:{stamp}"


def can_play(user: Any, track: Track) -> bool:
    """Peut-on lire cette piste ? Décision mise en cache 5 min ; la clé change à chaque
    modification de la piste (``updated_at``), donc une dépublication s'applique tout de suite."""
    m = membership(user)
    key = track_decision_key(m.user_id, track)
    cached = cache.get(key)
    if cached is not None:
        return bool(cached)
    node = track.source.node
    if not track.source.is_active:
        allowed = False
    elif can_publish(user, node) or can_moderate(user, node):
        allowed = True  # le staff écoute ses brouillons et les contenus signalés
    else:
        allowed = (
            track.hidden_at is None
            and track.published_at is not None
            and track.published_at <= timezone.now()
            and level_allowed(m, node, track.effective_visibility)
        )
    cache.set(key, allowed, settings.AUDIO_AUTHZ_CACHE_SECONDS)
    return allowed


def require_play(user: Any, track: Track) -> None:
    """Refus sans dire si la piste existe (404) pour un anonyme ou un non-membre."""
    if not can_play(user, track):
        raise NotFoundError("Cette piste est introuvable.", code="piste_introuvable")


def can_view_playlist(user: Any, playlist: Playlist) -> bool:
    if playlist.owner_id is not None:
        return playlist.visibility == Visibility.PUBLIC or (
            getattr(user, "is_authenticated", False) and playlist.owner_id == user.pk
        )
    source = playlist.source
    assert source is not None
    if can_publish(user, source.node):
        return True
    return playlist.published_at is not None and level_allowed(membership(user), source.node, playlist.visibility)
