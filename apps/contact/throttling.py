from typing import Any

from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle


class ContactRateThrottle(SimpleRateThrottle):
    """Formulaire public : quota strict par adresse IP (``CONTACT_THROTTLE_RATE``, 5/heure par défaut).

    Le taux est relu à chaque requête (réglable par ``override_settings`` en test) ; l'identité
    suit ``NUM_PROXIES`` comme les autres quotas."""

    scope = "contact"

    def get_rate(self) -> str | None:
        return settings.CONTACT_THROTTLE_RATE

    def get_cache_key(self, request: Any, view: Any) -> str:
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
