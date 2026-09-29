"""Limites de débit de la sonothèque (throttling DRF, même modèle que ``apps.contact``).

``POST /audio/evenements/`` est ouvert sans compte : on borne le nombre de lots par adresse IP
pour les anonymes (``NUM_PROXIES`` pour l'identité) et par compte pour les personnes connectées.
Les taux sont relus à chaque requête (réglables par ``override_settings`` en test) ; ``None``
désactive la limite.
"""

from typing import Any

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class _EventsThrottle(SimpleRateThrottle):
    setting_name = ""

    def get_rate(self) -> str | None:
        return getattr(settings, self.setting_name, None)

    def allow_request(self, request: Any, view: Any) -> bool:
        # Relit le taux à chaque requête (la classe le lit sinon une seule fois, à l'instanciation).
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)


class AudioEventsAnonThrottle(_EventsThrottle):
    """Anonymes : par adresse IP (``AUDIO_EVENTS_THROTTLE_RATE_ANON``)."""

    scope = "audio_events_anon"
    setting_name = "AUDIO_EVENTS_THROTTLE_RATE_ANON"

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        if getattr(request.user, "is_authenticated", False):
            return None
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class AudioEventsUserThrottle(_EventsThrottle):
    """Personnes connectées : par compte (``AUDIO_EVENTS_THROTTLE_RATE_USER``)."""

    scope = "audio_events_user"
    setting_name = "AUDIO_EVENTS_THROTTLE_RATE_USER"

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        if not getattr(request.user, "is_authenticated", False):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class _UserThrottle(_EventsThrottle):
    """Par compte ; ces routes exigent une connexion."""

    def get_cache_key(self, request: Any, view: Any) -> str | None:
        if not getattr(request.user, "is_authenticated", False):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}


class AudioDownloadThrottle(_UserThrottle):
    """``POST /audio/pistes/<id>/telechargement/`` (``AUDIO_DOWNLOAD_THROTTLE_RATE``)."""

    scope = "audio_download"
    setting_name = "AUDIO_DOWNLOAD_THROTTLE_RATE"


class AudioDownloadVerifyThrottle(_UserThrottle):
    """``POST /audio/telechargements/verifier/`` (``AUDIO_DOWNLOAD_VERIFY_THROTTLE_RATE``)."""

    scope = "audio_download_verify"
    setting_name = "AUDIO_DOWNLOAD_VERIFY_THROTTLE_RATE"
