"""Point de santé public : `GET /api/health/` (alias `/api/sante/`) (contrat Infrastructure, test de fumée).

Répond 200 quand la base et le cache (Redis) répondent, 503 sinon. Ne révèle
rien d'autre que l'état de ces deux dépendances ; aucune authentification,
aucune limitation de débit (le test de fumée et Uptime Kuma l'interrogent).
"""

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


def _base() -> bool:
    try:
        with connection.cursor() as curseur:
            curseur.execute("SELECT 1")
            return curseur.fetchone() == (1,)
    except Exception:  # noqa: BLE001 — toute erreur vaut « indisponible »
        return False


def _cache() -> bool:
    try:
        cache.set("sante:ping", "1", 5)
        return cache.get("sante:ping") == "1"
    except Exception:  # noqa: BLE001
        return False


@never_cache
@require_GET
def sante_view(request):
    etat = {"base": _base(), "cache": _cache()}
    ok = all(etat.values())
    return JsonResponse({"statut": "ok" if ok else "degrade", **etat}, status=200 if ok else 503)
