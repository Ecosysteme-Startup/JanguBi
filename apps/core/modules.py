"""Gel des modules hors V1 par configuration (ADR-006).

Le réglage ``JANGUBI_MODULES`` liste les modules actifs. Un module gelé garde
son code, ses modèles et ses migrations, mais ses routes ne sont plus exposées
et ses tâches Beat ne sont plus planifiées.

Les sous-modules s'écrivent ``<app>.<partie>`` (ex. ``liturgy.heures``) et ne
sont actifs que si leur module parent l'est aussi.
"""

from collections.abc import Iterable, Mapping
from typing import Any

# Modules « socle » : toujours actifs, non gelables (identité, erreurs, fichiers…).
# ``contact`` : formulaire public « Pour les paroisses », jamais gelé.
CORE_MODULES: frozenset[str] = frozenset(
    {"authentication", "users", "files", "notifications", "contact"}
)

# Modules et sous-modules qu'on peut activer ou geler.
FREEZABLE_MODULES: tuple[str, ...] = (
    "bible",
    "bible.avance",  # Lectio divina, plans de lecture, notes d'homélie
    "rosary",
    "rosary.communautaire",
    "liturgy",
    "liturgy.heures",  # Liturgie des Heures (pas d'accord AELF)
    "messaging",
    "confessions",
    "documents",
    "news",
    "hierarchy",
    "agenda",
    "dashboards",
    "donations",  # ADR-017 : actif, mais la collecte exige aussi l'activation du nœud
)

# Périmètre V1 (plan L0.4) : tout sauf les modules gelés par l'ADR-006.
FROZEN_BY_DEFAULT: frozenset[str] = frozenset(
    {
        "bible.avance",
        "rosary.communautaire",
        "liturgy.heures",
    }
)

V1_DEFAULT_MODULES: tuple[str, ...] = tuple(m for m in FREEZABLE_MODULES if m not in FROZEN_BY_DEFAULT)


def is_module_active(name: str, *, active: Iterable[str] | None = None) -> bool:
    """Vrai si le module (ou sous-module) ``name`` est actif."""
    if name in CORE_MODULES:
        return True
    if active is None:
        from django.conf import settings

        active = settings.JANGUBI_MODULES
    active_set = set(active)
    parent = name.split(".", 1)[0]
    if parent != name and parent not in active_set:
        return False
    return name in active_set


def task_module(task_path: str) -> str | None:
    """``apps.messaging.tasks.foo`` → ``messaging`` ; ``None`` hors de ``apps.``."""
    parts = task_path.split(".")
    if len(parts) < 2 or parts[0] != "apps":
        return None
    return parts[1]


def filter_beat_schedule(
    schedule: Mapping[str, Mapping[str, Any]], *, active: Iterable[str]
) -> dict[str, Mapping[str, Any]]:
    """Retire du planning Beat les tâches des modules gelés.

    Une entrée peut préciser son sous-module via la clé ``module`` (retirée du
    résultat, Celery ne la connaît pas) ; sinon le module est déduit du chemin
    de la tâche.
    """
    active_set = set(active)
    kept: dict[str, Mapping[str, Any]] = {}
    for name, entry in schedule.items():
        module = entry.get("module") or task_module(str(entry["task"]))
        if module is None or module not in FREEZABLE_MODULES or is_module_active(module, active=active_set):
            kept[name] = {k: v for k, v in entry.items() if k != "module"}
    return kept
