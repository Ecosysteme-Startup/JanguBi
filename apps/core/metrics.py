"""Point d'exposition Prometheus ``/metrics`` (django-prometheus), protégé (lot B2).

Accès accordé si :
- l'en-tête ``Authorization: Bearer <METRICS_TOKEN>`` est correct (comparaison à temps constant) ;
- OU l'adresse du client (``REMOTE_ADDR``, jamais ``X-Forwarded-For`` que le client écrit) est
  dans ``METRICS_ALLOWED_CIDRS`` ET la requête n'est pas passée par le proxy public
  (pas d'en-tête ``X-Forwarded-For``) : Prometheus interroge le conteneur directement.

Sinon : 404, pour ne pas signaler l'existence du point d'accès.
"""

import hmac
import ipaddress
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse


def _token_ok(request: HttpRequest) -> bool:
    expected = settings.METRICS_TOKEN
    if not expected:
        return False
    header = request.META.get("HTTP_AUTHORIZATION", "")
    scheme, _, value = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(value.strip().encode(), expected.encode())


def _ip_ok(request: HttpRequest) -> bool:
    if request.META.get("HTTP_X_FORWARDED_FOR"):
        return False
    try:
        address = ipaddress.ip_address(request.META.get("REMOTE_ADDR", ""))
    except ValueError:
        return False
    for cidr in settings.METRICS_ALLOWED_CIDRS:
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def metrics_allowed(request: HttpRequest) -> bool:
    return bool(settings.METRICS_ENABLED) and (_token_ok(request) or _ip_ok(request))


@transaction.non_atomic_requests  # pas de transaction (ATOMIC_REQUESTS) pour un simple export
def metrics_view(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    if not metrics_allowed(request):
        raise Http404()
    from django_prometheus.exports import ExportToDjangoView  # type: ignore[import-untyped]

    return ExportToDjangoView(request)
