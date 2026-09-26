"""Contexte de la requête HTTP en cours, lisible depuis les services (journal d'audit).

Les services n'ont pas la requête : le middleware ``RequestContextMiddleware`` dépose
l'adresse IP du client dans une ``ContextVar`` que ``apps.hierarchy.audit.audit_log`` lit.
Hors requête (Celery, commandes, WebSocket), l'adresse est ``None``.
"""

import ipaddress
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from rest_framework.settings import api_settings

_client_ip: ContextVar[str | None] = ContextVar("jangubi_client_ip", default=None)

# Minimisation (loi 2008-12, RG-10) : le journal ne garde que le réseau, pas la machine.
IPV4_PREFIX = 24
IPV6_PREFIX = 48


def client_ip(meta: dict[str, Any]) -> str | None:
    """Adresse du client derrière ``NUM_PROXIES`` mandataires de confiance (même règle que
    l'identité de throttling de DRF) ; ``None`` si elle est absente ou mal formée."""
    xff = meta.get("HTTP_X_FORWARDED_FOR")
    remote = meta.get("REMOTE_ADDR")
    num_proxies = api_settings.NUM_PROXIES
    if xff and num_proxies:
        addresses = [a.strip() for a in xff.split(",") if a.strip()]
        candidate = addresses[-min(num_proxies, len(addresses))] if addresses else remote
    else:
        candidate = remote
    try:
        return str(ipaddress.ip_address(candidate)) if candidate else None
    except ValueError:
        return None


def ip_truncate(ip: str | None) -> str | None:
    """IPv4 → /24 (``203.0.113.0``), IPv6 → /48. Valeur invalide → ``None``."""
    if not ip:
        return None
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = IPV4_PREFIX if address.version == 4 else IPV6_PREFIX
    return str(ipaddress.ip_network(f"{address}/{prefix}", strict=False).network_address)


def current_client_ip() -> str | None:
    return _client_ip.get()


class RequestContextMiddleware:
    """Dépose l'adresse du client pour la durée de la requête (synchrone ou asynchrone)."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response
        if iscoroutinefunction(get_response):
            markcoroutinefunction(self)

    def __call__(self, request: Any) -> Any:
        if iscoroutinefunction(self):
            return self.__acall__(request)
        token = _client_ip.set(client_ip(request.META))
        try:
            return self.get_response(request)
        finally:
            _client_ip.reset(token)

    async def __acall__(self, request: Any) -> Any:
        token = _client_ip.set(client_ip(request.META))
        try:
            return await self.get_response(request)
        finally:
            _client_ip.reset(token)
